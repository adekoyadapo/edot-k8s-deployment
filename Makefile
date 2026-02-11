SHELL := /bin/bash

CLUSTER_NAME ?= edot-observability
OBS_NAMESPACE ?= observability-lab
APP_NAMESPACE ?= demo-app
ELASTIC_VERSION ?= 8.19.11
ECK_VERSION ?= 3.3.0
EDOT_VERSION ?= 9.2.5
BASE_DOMAIN_FILE ?= .env

.PHONY: up simulate status logs down

up:
	@./hack/detect-domain.sh
	@if k3d cluster list | rg -q "^$(CLUSTER_NAME)"; then \
		echo "k3d cluster $(CLUSTER_NAME) already exists"; \
	else \
		k3d cluster create --config k3d/cluster.yaml; \
	fi
	@./hack/metrics-server.sh
	@kubectl get ns $(OBS_NAMESPACE) >/dev/null 2>&1 || kubectl create ns $(OBS_NAMESPACE)
	@kubectl get ns $(APP_NAMESPACE) >/dev/null 2>&1 || kubectl create ns $(APP_NAMESPACE)
	@kubectl get ns elastic-system >/dev/null 2>&1 || kubectl create ns elastic-system
	@curl -fsSL https://download.elastic.co/downloads/eck/$(ECK_VERSION)/crds.yaml -o elastic/eck-crds.yaml
	@kubectl apply -f elastic/eck-crds.yaml
	@curl -fsSL https://download.elastic.co/downloads/eck/$(ECK_VERSION)/operator.yaml -o elastic/eck-operator.yaml
	@kubectl apply -f elastic/eck-operator.yaml
	@kubectl -n elastic-system rollout status statefulset/elastic-operator --timeout=10m
	@until kubectl get crd elasticsearches.elasticsearch.k8s.elastic.co >/dev/null 2>&1; do sleep 5; done
	@until kubectl get crd kibanas.kibana.k8s.elastic.co >/dev/null 2>&1; do sleep 5; done
	@kubectl wait --for=condition=Established crd/elasticsearches.elasticsearch.k8s.elastic.co --timeout=10m
	@kubectl wait --for=condition=Established crd/kibanas.kibana.k8s.elastic.co --timeout=10m
	@kubectl -n $(OBS_NAMESPACE) apply -f elastic/elasticsearch.yaml
	@kubectl -n $(OBS_NAMESPACE) apply -f elastic/kibana.yaml
	@kubectl -n $(OBS_NAMESPACE) create configmap edot-agent-config \
		--from-file=otelcol-config.yaml=otel/configs/agent-config.yaml \
		--dry-run=client -o yaml | kubectl apply -f -
	@kubectl -n $(OBS_NAMESPACE) create configmap edot-gateway-config \
		--from-file=otelcol-config.yaml=otel/configs/gateway-config.yaml \
		--dry-run=client -o yaml | kubectl apply -f -
	@kubectl -n $(OBS_NAMESPACE) create configmap edot-cluster-config \
		--from-file=otelcol-config.yaml=otel/configs/cluster-config.yaml \
		--dry-run=client -o yaml | kubectl apply -f -
	@kubectl -n $(OBS_NAMESPACE) apply -f otel/rbac.yaml
	@kubectl -n $(OBS_NAMESPACE) apply -f otel/edot-agent.yaml
	@kubectl -n $(OBS_NAMESPACE) apply -f otel/edot-cluster.yaml
	@kubectl -n $(OBS_NAMESPACE) apply -f otel/edot-gateway.yaml
	@docker build -t edot-frontend:1.0.0 app/src/frontend
	@docker build -t edot-backend:1.0.0 app/src/backend
	@k3d image import -c $(CLUSTER_NAME) edot-frontend:1.0.0 edot-backend:1.0.0
	@kubectl apply -f app/k8s/namespace.yaml
	@kubectl -n $(APP_NAMESPACE) apply -f app/k8s/configmaps-secrets.yaml
	@kubectl -n $(APP_NAMESPACE) apply -f app/k8s/database.yaml
	@kubectl -n $(APP_NAMESPACE) apply -f app/k8s/backend.yaml
	@kubectl -n $(APP_NAMESPACE) apply -f app/k8s/frontend.yaml
	@. $(BASE_DOMAIN_FILE) && export BASE_DOMAIN && envsubst < app/k8s/ingress.yaml | kubectl -n $(APP_NAMESPACE) apply -f -
	@. $(BASE_DOMAIN_FILE) && export BASE_DOMAIN && envsubst < elastic/kibana-ingress.yaml | kubectl -n $(OBS_NAMESPACE) apply -f -
	@./hack/wait-ready.sh
	@./hack/print-endpoints.sh

simulate:
	@kubectl -n $(APP_NAMESPACE) create configmap k6-scripts \
		--from-file=scenario.js=load/scripts/scenario.js \
		--dry-run=client -o yaml | kubectl apply -f -
	@kubectl -n $(APP_NAMESPACE) delete job k6-load --ignore-not-found
	@kubectl -n $(APP_NAMESPACE) apply -f load/k6.yaml
	@echo "Waiting for HPA to react to load..."
	@sleep 30
	@kubectl -n $(OBS_NAMESPACE) get hpa edot-gateway-hpa
	@kubectl -n $(OBS_NAMESPACE) get deploy edot-gateway

status:
	@kubectl -n $(OBS_NAMESPACE) get pods
	@kubectl -n $(OBS_NAMESPACE) get svc
	@kubectl -n $(OBS_NAMESPACE) get hpa
	@kubectl -n $(APP_NAMESPACE) get pods
	@./hack/print-endpoints.sh
	@echo "Telemetry check: Kibana > Observability > APM, Logs, Metrics, Infrastructure."

logs:
	@kubectl -n $(OBS_NAMESPACE) logs deploy/edot-gateway --tail=200


down:
	@k3d cluster delete $(CLUSTER_NAME)
	@./hack/clean.sh
