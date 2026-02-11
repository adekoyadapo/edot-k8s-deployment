#!/usr/bin/env bash
set -euo pipefail

if kubectl -n kube-system get deployment metrics-server >/dev/null 2>&1; then
  kubectl patch clusterrole system:metrics-server --type='json' \
    -p='[{"op":"add","path":"/rules/0/resources/-","value":"nodes/metrics"}]' >/dev/null 2>&1 || true
  kubectl -n kube-system patch deployment metrics-server --type='json' \
    -p='[{"op":"add","path":"/spec/template/spec/containers/0/args/-","value":"--kubelet-insecure-tls"}]' >/dev/null 2>&1 || true
  kubectl -n kube-system rollout restart deployment/metrics-server
  kubectl -n kube-system rollout status deployment/metrics-server --timeout=5m
else
  kubectl apply -f k3d/metrics-server.yaml
  kubectl -n kube-system rollout status deployment/metrics-server --timeout=5m
fi
