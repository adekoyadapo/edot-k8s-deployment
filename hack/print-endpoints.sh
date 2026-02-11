#!/usr/bin/env bash
set -euo pipefail

OBS_NAMESPACE="${OBS_NAMESPACE:-observability-lab}"
BASE_DOMAIN_FILE="${BASE_DOMAIN_FILE:-.env}"

if [ -f "$BASE_DOMAIN_FILE" ]; then
  . "$BASE_DOMAIN_FILE"
fi

if [ -z "${BASE_DOMAIN:-}" ]; then
  echo "BASE_DOMAIN not set. Run ./hack/detect-domain.sh first." >&2
  exit 1
fi

ES_PASSWORD="$(kubectl -n "$OBS_NAMESPACE" get secret quickstart-es-elastic-user -o jsonpath='{.data.elastic}' | base64 --decode)"

cat <<EOM
Endpoints:
  App:    http://app.${BASE_DOMAIN}/
  Kibana: http://kb.${BASE_DOMAIN}/

Elasticsearch:
  URL:      https://quickstart-es-http.${OBS_NAMESPACE}.svc:9200
  Username: elastic
  Password: ${ES_PASSWORD}
EOM
