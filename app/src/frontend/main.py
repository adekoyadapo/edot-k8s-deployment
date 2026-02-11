import os
import time
import logging
import json
import requests
from fastapi import FastAPI
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
from opentelemetry.instrumentation.requests import RequestsInstrumentor
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


setup_otel(os.getenv("OTEL_SERVICE_NAME", "frontend"))
FastAPIInstrumentor.instrument_app(app)
RequestsInstrumentor().instrument()
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
        service_name = getattr(record, "otelServiceName", "") or os.getenv("OTEL_SERVICE_NAME", "frontend")
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

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8080")
tracer = trace.get_tracer("frontend")
meter = metrics.get_meter("frontend")
request_counter = meter.create_counter("frontend.requests", description="Frontend requests")
logger = logging.getLogger("frontend")


@app.get("/")
def index() -> str:
    start = time.time()
    response = requests.get(f"{BACKEND_URL}/api", timeout=2)
    elapsed_ms = int((time.time() - start) * 1000)
    request_counter.add(1, {"route": "/"})
    data = response.json()
    logger.info("frontend index", extra={"backend_hits": data.get("hits"), "latency_ms": elapsed_ms})
    return (
        f"<h1>Frontend</h1>"
        f"<p>Backend message: {data.get('message')}</p>"
        f"<p>DB hits: {data.get('hits')}</p>"
        f"<p>Latency: {elapsed_ms}ms</p>"
    )


@app.get("/simulate")
def simulate() -> dict:
    with tracer.start_as_current_span("frontend.simulate") as span:
        span.set_attribute("client.workload", "mix")
        requests.post(f"{BACKEND_URL}/api/items", json={"key": "alpha", "value": "one"}, timeout=2)
        requests.get(f"{BACKEND_URL}/api/items/alpha", timeout=2)
        requests.put(f"{BACKEND_URL}/api/items/alpha", json={"key": "alpha", "value": "two"}, timeout=2)
        requests.delete(f"{BACKEND_URL}/api/items/alpha", timeout=2)
        requests.get(f"{BACKEND_URL}/api/slow", timeout=2)
    request_counter.add(1, {"route": "/simulate"})
    logger.info("frontend simulate complete")
    return {"status": "ok"}


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
