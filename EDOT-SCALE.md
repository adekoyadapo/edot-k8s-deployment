# EDOT Gateway Scaling Guide (Kubernetes)

This document explains how EDOT is scaled in this lab, how the simulation workload behaves, what the HPA should do, and how this maps to production-scale architectures.

## Architecture Flow (Lab)

```
                 ┌──────────────────┐
                 │    Frontend      │
                 │  FastAPI + OTel  │
                 └────────┬─────────┘
                          │ HTTP
                          ▼
                 ┌──────────────────┐
                 │     Backend      │
                 │ FastAPI + OTel   │
                 └────────┬─────────┘
                          │ Redis
                          ▼
                 ┌──────────────────┐
                 │     Redis DB     │
                 └──────────────────┘

   OTLP HTTP           OTLP gRPC                  HTTPS
Frontend/Backend ──► EDOT Agent DS ──► EDOT Gateway (HPA) ──► Elasticsearch ──► Kibana
                         ▲    ▲
                         │    └── EDOT Cluster (Deployment) ──► K8s cluster metrics + events
                         └────── Kubelet metrics + container logs (filelog)
```

**Key components**
- **EDOT Agent (DaemonSet)**: receives OTLP from apps, tails container logs, scrapes kubelet metrics.
- **EDOT Cluster (Deployment)**: collects cluster metrics and events.
- **EDOT Gateway (Deployment + HPA)**: buffers/batches, enriches, exports to Elasticsearch.


## Where The Configuration Lives (Code References)

- **Gateway HPA + Deployment**: `otel/edot-gateway.yaml`
- **Gateway pipeline config**: `otel/configs/gateway-config.yaml`
- **Agent pipeline config**: `otel/configs/agent-config.yaml`
- **Cluster collector config**: `otel/configs/cluster-config.yaml`
- **App namespaces and ingress**: `app/k8s/namespace.yaml`, `app/k8s/ingress.yaml`, `elastic/kibana-ingress.yaml`
- **App instrumentation**:
  - Frontend: `app/src/frontend/main.py`
  - Backend: `app/src/backend/main.py`
- **Simulation workload**: `load/scripts/scenario.js`, `load/k6.yaml`


## Simulation Workflow (What Happens)

The simulation is triggered by:

```
make simulate
```

This applies a k6 Job using `load/k6.yaml`, which runs `load/scripts/scenario.js`.

**Simulation workload behavior** (from `load/scripts/scenario.js`):
- GET `/` (frontend)
- GET `/simulate` (frontend)
- POST `/api/items` (backend)
- GET `/api/items/{key}`
- PUT `/api/items/{key}`
- DELETE `/api/items/{key}`
- GET `/api/slow`

This generates:
- **Traces** across frontend → backend → redis
- **Metrics** (request counters + latency histogram)
- **Logs** (JSON logs with `trace.id`, `span.id`, ECS fields)

## Suggested Timeline (What To Watch)

The timings below are based on a typical run of `make simulate` in this lab with current HPA settings (80% CPU/memory targets). Expect ±1–2 minutes variance depending on local resources.

**0:00 – 0:30**
- k6 Job starts (see `demo-app` namespace Job `k6-load`).
- First traces/logs appear in Kibana.
- `edot-gateway` stays at 1 replica while CPU/memory ramp up.

**1:00 – 3:00**
- HPA metrics become stable (metrics-server warms up).
- Gateway begins scaling up if CPU/memory exceed 80%.

**~3:00 – 8:00**
- Gateway replicas increase to 2–4 (depending on host capacity).
- HPA events show “SuccessfulRescale”.

**~8:00 – 12:00**
- Load continues; gateway steady-state. Logs/metrics volume increases.
- Kibana shows more log volume, APM traces, and metrics.

**After load ends (~5m duration in `scenario.js`)**
- Gateway scales down (scale-down stabilization is 30s).
- Expect 1–2 step reductions every 15s until back to 1 replica.

### Example HPA Event Pattern

```
New size: 3; reason: cpu resource utilization (percentage of request) above target
New size: 4; reason: cpu resource utilization (percentage of request) above target
New size: 3; reason: All metrics below target
New size: 2; reason: All metrics below target
```

### What to check in real time

```
kubectl -n observability-lab get hpa edot-gateway-hpa
kubectl -n observability-lab describe hpa edot-gateway-hpa
kubectl -n observability-lab get deploy edot-gateway
```


## Expected HPA Reaction

HPA for EDOT gateway is defined in `otel/edot-gateway.yaml` and is driven by CPU and memory utilization.

With the current config:
- **Scale-up target**: 80% CPU and 80% memory
- **Max replicas**: 4
- **Scale-down behavior**: fast scale-down (30s stabilization, aggressive policy)

**Expected behavior**:
1. Load starts (k6 Job).
2. EDOT gateway CPU/memory rises as telemetry volume increases.
3. HPA scales gateway replicas upward when utilization exceeds 80%.
4. When load stops, replicas scale down quickly per the scale-down policy.

You can confirm this via:
```
kubectl -n observability-lab get hpa edot-gateway-hpa
kubectl -n observability-lab describe hpa edot-gateway-hpa
```


## Log Flow Expectations

**App logs** are emitted as structured JSON (ECS-like) with:
- `trace.id`
- `span.id`
- `service.name`
- `service.version`
- `event.dataset`

**Log pipeline flow**:

```
App stdout → EDOT Agent filelog → EDOT Gateway transform/logs → Elasticsearch
```

Gateway log transforms ensure:
- `log.level` is derived from `severity_text` or JSON fields
- `trace.id`, `span.id`, `service.name` are promoted to attributes

This prevents Kibana “(missing value)” in log-level breakdowns.


## Production-Scale Guidance

### Gateway Scaling Strategy
- Use **multiple gateway replicas** with HPA/VPA.
- Apply **resource requests/limits** to get accurate scaling signals.
- Consider **sharded gateways** per environment or business unit.

### Agent vs Gateway Scaling
- **Scale agents** when edge collection is heavy (logs/metrics volume).
- **Scale gateways** when backend export throughput is the bottleneck.

### Reliability Recommendations
- Always enable `memory_limiter` and `batch` processors.
- Use bounded queues and retry backoff.
- Split log and metric pipelines if one signal dominates.

### Observability at Scale
- Separate environments (dev/stage/prod) into distinct namespaces or clusters.
- Use dedicated Elasticsearch tiers for high-volume telemetry.
- Track ingestion rates to size gateway pools.


## Reference Diagram (Text)

```
[ Apps ] --OTLP--> [ EDOT Agent DS ] --OTLP--> [ EDOT Gateway HPA ] --HTTPS--> [ Elasticsearch ] --> [ Kibana ]
                 \                                          \
                  \-- Kubelet Metrics + Logs                \-- Cluster Metrics + Events
                    (filelog + kubeletstats)                (EDOT Cluster)
```


## Summary

This lab demonstrates the full EDOT pipeline with:
- A realistic 3-tier app
- Full trace + metric + log collection
- Kubernetes telemetry (node/cluster/logs)
- HPA-driven scaling of the gateway

The simulation validates how EDOT scales and how telemetry volume influences gateway resource usage. For production, use multiple gateway replicas, apply sharding, and tune pipelines to avoid bottlenecks.
