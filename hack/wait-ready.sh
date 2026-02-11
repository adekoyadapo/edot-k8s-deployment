#!/usr/bin/env bash
set -euo pipefail

OBS_NAMESPACE="${OBS_NAMESPACE:-observability-lab}"
APP_NAMESPACE="${APP_NAMESPACE:-demo-app}"

kubectl -n elastic-system rollout status statefulset/elastic-operator --timeout=10m
kubectl -n "$OBS_NAMESPACE" wait --for=condition=ready pod -l elasticsearch.k8s.elastic.co/cluster-name=quickstart --timeout=10m
kubectl -n "$OBS_NAMESPACE" wait --for=condition=ready pod -l kibana.k8s.elastic.co/name=kb --timeout=10m
kubectl -n "$OBS_NAMESPACE" wait --for=condition=available deployment/edot-gateway --timeout=10m
kubectl -n "$OBS_NAMESPACE" wait --for=condition=available deployment/edot-cluster --timeout=10m
kubectl -n "$APP_NAMESPACE" wait --for=condition=available deployment/frontend --timeout=10m
kubectl -n "$APP_NAMESPACE" wait --for=condition=available deployment/backend --timeout=10m
kubectl -n "$APP_NAMESPACE" wait --for=condition=available deployment/redis --timeout=10m
kubectl -n "$OBS_NAMESPACE" wait --for=condition=ready pod --all --timeout=10m
kubectl -n "$APP_NAMESPACE" wait --for=condition=ready pod --all --timeout=10m
