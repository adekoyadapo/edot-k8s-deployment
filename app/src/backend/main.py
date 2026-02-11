import os
import time
import random
import logging
import json
import redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from opentelemetry import trace, metrics
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.logging import LoggingInstrumentor

app = FastAPI()


def setup_otel(service_name: str) -> None:
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://edot-agent:4318").rstrip("/")
    resource = Resource.create({
        "service.name": service_name,
        "deployment.environment": os.getenv("DEPLOYMENT_ENV", "local"),
    })

    tracer_provider = TracerProvider(resource=resource)
    tracer_provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces"))
    )
    trace.set_tracer_provider(tracer_provider)

    logger_provider = LoggerProvider(resource=resource)
    logger_provider.add_log_record_processor(
        BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{endpoint}/v1/logs"))
    )
    handler = LoggingHandler(level=logging.INFO, logger_provider=logger_provider)
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)

    metric_reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics"),
        export_interval_millis=5000,
    )
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)


setup_otel(os.getenv("OTEL_SERVICE_NAME", "backend"))
FastAPIInstrumentor.instrument_app(app)
RedisInstrumentor().instrument()
LoggingInstrumentor().instrument(set_logging_format=True)

def parse_resource_attributes(raw: str) -> dict:
    attrs = {}
    if not raw:
        return attrs
    for part in raw.split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        attrs[key.strip()] = value.strip()
    return attrs


RESOURCE_ATTRS = parse_resource_attributes(os.getenv("OTEL_RESOURCE_ATTRIBUTES", ""))


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        service_name = getattr(record, "otelServiceName", "") or os.getenv("OTEL_SERVICE_NAME", "backend")
        payload = {
            "@timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S.%fZ"),
            "log.level": record.levelname,
            "message": record.getMessage(),
            "logger.name": record.name,
            "trace.id": getattr(record, "otelTraceID", ""),
            "span.id": getattr(record, "otelSpanID", ""),
            "service.name": service_name,
            "service.version": RESOURCE_ATTRS.get("service.version", ""),
            "service.namespace": RESOURCE_ATTRS.get("service.namespace", ""),
            "deployment.environment": RESOURCE_ATTRS.get("deployment.environment", ""),
            "host.name": os.getenv("HOSTNAME", ""),
            "event.dataset": f"{service_name}.log",
        }
        for key, value in record.__dict__.items():
            if key in payload or key.startswith("otel"):
                continue
            if key in ("args", "msg", "levelname", "levelno", "pathname", "filename", "module",
                       "exc_info", "exc_text", "stack_info", "lineno", "funcName", "created",
                       "msecs", "relativeCreated", "thread", "threadName", "processName", "process"):
                continue
            payload[key] = value
        return json.dumps(payload)


handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
root_logger = logging.getLogger()
root_logger.handlers = [handler]
root_logger.setLevel(logging.INFO)

REDIS_HOST = os.getenv("REDIS_HOST", "redis")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

meter = metrics.get_meter("backend")
request_counter = meter.create_counter("backend.requests", description="Backend requests")
latency_hist = meter.create_histogram("backend.latency_ms", description="Backend latency ms")
tracer = trace.get_tracer("backend")
logger = logging.getLogger("backend")


class Item(BaseModel):
    key: str
    value: str


@app.get("/api")
def api() -> dict:
    start = time.time()
    with tracer.start_as_current_span("redis.get_and_set") as span:
        hits = redis_client.incr("hits")
        span.set_attribute("db.system", "redis")
        time.sleep(0.01)
    duration_ms = int((time.time() - start) * 1000)
    request_counter.add(1, {"route": "/api"})
    latency_hist.record(duration_ms, {"route": "/api"})
    logger.info("backend api", extra={"hits": hits, "latency_ms": duration_ms})
    return {"message": "hello from backend", "hits": hits}


@app.post("/api/items")
def create_item(item: Item) -> dict:
    start = time.time()
    with tracer.start_as_current_span("redis.create_item") as span:
        span.set_attribute("item.key", item.key)
        ok = redis_client.set(item.key, item.value)
        time.sleep(0.01)
    if not ok:
        raise HTTPException(status_code=500, detail="failed to write")
    duration_ms = int((time.time() - start) * 1000)
    request_counter.add(1, {"route": "POST /api/items"})
    latency_hist.record(duration_ms, {"route": "POST /api/items"})
    logger.info("item created", extra={"key": item.key, "latency_ms": duration_ms})
    return {"status": "created", "key": item.key}


@app.get("/api/items/{key}")
def get_item(key: str) -> dict:
    start = time.time()
    with tracer.start_as_current_span("redis.get_item") as span:
        span.set_attribute("item.key", key)
        value = redis_client.get(key)
        time.sleep(0.005)
    duration_ms = int((time.time() - start) * 1000)
    request_counter.add(1, {"route": "GET /api/items"})
    latency_hist.record(duration_ms, {"route": "GET /api/items"})
    if value is None:
        logger.warning("item not found", extra={"key": key})
        raise HTTPException(status_code=404, detail="not found")
    logger.info("item fetched", extra={"key": key, "latency_ms": duration_ms})
    return {"key": key, "value": value}


@app.put("/api/items/{key}")
def update_item(key: str, item: Item) -> dict:
    start = time.time()
    with tracer.start_as_current_span("redis.update_item") as span:
        span.set_attribute("item.key", key)
        redis_client.set(key, item.value)
        time.sleep(0.008)
    duration_ms = int((time.time() - start) * 1000)
    request_counter.add(1, {"route": "PUT /api/items"})
    latency_hist.record(duration_ms, {"route": "PUT /api/items"})
    logger.info("item updated", extra={"key": key, "latency_ms": duration_ms})
    return {"status": "updated", "key": key}


@app.delete("/api/items/{key}")
def delete_item(key: str) -> dict:
    start = time.time()
    with tracer.start_as_current_span("redis.delete_item") as span:
        span.set_attribute("item.key", key)
        deleted = redis_client.delete(key)
        time.sleep(0.004)
    duration_ms = int((time.time() - start) * 1000)
    request_counter.add(1, {"route": "DELETE /api/items"})
    latency_hist.record(duration_ms, {"route": "DELETE /api/items"})
    if deleted == 0:
        logger.warning("item delete miss", extra={"key": key})
        raise HTTPException(status_code=404, detail="not found")
    logger.info("item deleted", extra={"key": key, "latency_ms": duration_ms})
    return {"status": "deleted", "key": key}


@app.get("/api/slow")
def slow() -> dict:
    delay = random.uniform(0.05, 0.2)
    with tracer.start_as_current_span("backend.slow_work") as span:
        span.set_attribute("delay_ms", int(delay * 1000))
        time.sleep(delay)
    request_counter.add(1, {"route": "GET /api/slow"})
    latency_hist.record(int(delay * 1000), {"route": "GET /api/slow"})
    logger.info("slow request", extra={"delay_ms": int(delay * 1000)})
    return {"status": "ok", "delay_ms": int(delay * 1000)}


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
