# k3d + ECK + EDOT Observability Lab

A fully reproducible, local Kubernetes observability lab using k3d, Elastic Cloud on Kubernetes (ECK), and Elastic Distribution of OpenTelemetry (EDOT). This brings up a 3‑tier app, OTLP ingestion, and an EDOT gateway with HPA scaling.

## Quick Start

Prereqs: `docker`, `kubectl`, `k3d`, `make`, `envsubst`.

1. `make up`
2. `make status`
3. `make simulate`
4. `make down`

The `make up` target prints:
- App URL: `http://app.<BASE_DOMAIN>/`
- Kibana URL: `http://kb.<BASE_DOMAIN>/`
- Elasticsearch credentials

Namespaces:
- Observability stack and EDOT: `observability-lab`
- Demo app: `demo-app`

## Architecture

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

## Architectural Flow

- **Apps emit telemetry (traces, metrics, logs)** using OpenTelemetry SDKs.
- **EDOT Agent (DaemonSet)** receives OTLP from apps, scrapes kubelet metrics, and tails container logs.
- **EDOT Cluster (Deployment)** collects cluster-wide metrics and events.
- **EDOT Gateway (Deployment + HPA)** batches, enriches, and exports to Elasticsearch.
- **Elasticsearch + Kibana (ECK)** store and visualize all observability data.

## Key Additions In This Lab

- App moved to **`demo-app`** namespace; observability stack is **`observability-lab`**.
- Full CRUD API + slow path for realistic traces:
  - `GET /api`, `POST/GET/PUT/DELETE /api/items`, `GET /api/slow`.
- Frontend `/simulate` generates multi-step traces across tiers.
- **OTLP logs** from app with ECS-style JSON fields (`trace.id`, `span.id`, `service.name`, etc.).
- **Kubernetes telemetry** collected via EDOT Agent + EDOT Cluster collectors.
- **Gateway HPA** tuned for realistic thresholds and fast scale-down.

## Version Pinning

- ECK operator: 3.3.0
- Elastic Stack: 8.19.x (tested: 8.19.11)
- EDOT collector image: 9.2.x (tested: 9.2.5)
- k3s (k3d): v1.31.4-k3s1
- k6: 0.49.0
- metrics-server: v0.7.2
- Redis: 7.2
- Python: 3.11

Compatibility note: With EDOT Collector 9.x and Elastic Stack 8.18/8.19, the gateway config uses the stack-aligned (deprecated) `elastictrace` and `elasticinframetrics` processors for Kibana Observability UI compatibility.

## EDOT Gateway Scaling

The gateway Deployment starts with 1 replica and scales via HPA (CPU + memory). `make simulate` runs k6 load and prints HPA/Deployment state to show scaling. HPA targets are set to **80%** utilization with aggressive scale-down behavior.

Kubernetes telemetry is collected by:
- EDOT Agent (DaemonSet) for node metrics, container logs, and application OTLP.
- EDOT Cluster (Deployment) for cluster-level metrics.
- EDOT Gateway for preprocessing and ingestion into Elasticsearch.

Best practices:
- Scale gateways when backend ingestion becomes a bottleneck; scale agents for edge collection pressure.
- Always set `memory_limiter` and `batch` processors.
- Use resource requests/limits so HPA has accurate signals.
- Avoid collector bottlenecks by sizing batch limits and keeping queues bounded.

### Enterprise / Large-Scale Guidance

- **Gateway scaling strategy**
  - Use multiple replicas with HPA/VPA and set explicit CPU/memory limits.
  - Prefer **multiple gateway deployments** per environment or tenant for isolation.
  - Use **sharding by namespace/team** to avoid noisy-neighbor effects.

- **Agent vs Gateway**
  - Scale **agents** when edge collection CPU/IO is the bottleneck.
  - Scale **gateways** when export/backpressure or backend ingest rate is the bottleneck.

- **Resilience**
  - Enable **batch + memory limiter** everywhere.
  - Consider **queueing** or **retry** with bounded memory to avoid OOM.
  - Separate **logs** and **metrics** pipelines if one signal dominates.

## What The Simulation Achieves

`make simulate` runs a k6 workload that:
- Exercises GET/POST/PUT/DELETE routes and a slow path.
- Generates multi-span traces across frontend → backend → Redis.
- Produces log volume and metrics to trigger EDOT gateway autoscaling.

This demonstrates how gateway scaling reacts to sustained telemetry load and how traces/logs/metrics appear in Kibana.

## Validation

`make status` confirms:
- All pods ready
- URLs for Kibana and the app
- Elasticsearch credentials

To confirm telemetry in Kibana:
1. Open Kibana and log in as `elastic`.
2. Go to **Observability → APM** and confirm the `frontend` and `backend` services.
3. Go to **Observability → Metrics** and confirm custom `backend.requests` metrics.
4. Go to **Observability → Infrastructure** to see Kubernetes inventory and node metrics.
5. Go to **Observability → Logs** to see container logs.

## Troubleshooting

- **No data in Kibana**: check `kubectl -n observability-lab logs deploy/edot-gateway` and `kubectl -n observability-lab logs ds/edot-agent`.
- **Kibana ingress 404/502**: ensure Traefik is running and the `kb.<BASE_DOMAIN>` ingress exists.
- **TLS errors to Elasticsearch**: verify the gateway has the `quickstart-es-http-certs-public` secret mounted.
- **Cluster port conflicts**: ensure ports 80/443 are free on the host.
