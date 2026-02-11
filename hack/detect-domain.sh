#!/usr/bin/env bash
set -euo pipefail

BASE_DOMAIN_FILE="${BASE_DOMAIN_FILE:-.env}"
HOST_IP=""

if command -v ip >/dev/null 2>&1; then
  HOST_IP="$(ip route get 1 | awk '{for (i=1;i<=NF;i++) if ($i=="src") {print $(i+1); exit}}')"
fi

if [ -z "$HOST_IP" ] && command -v ipconfig >/dev/null 2>&1; then
  HOST_IP="$(ipconfig getifaddr en0 2>/dev/null || true)"
  if [ -z "$HOST_IP" ]; then
    HOST_IP="$(ipconfig getifaddr en1 2>/dev/null || true)"
  fi
fi

if [ -z "$HOST_IP" ]; then
  HOST_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
fi

if [ -z "$HOST_IP" ]; then
  echo "Failed to detect host IP" >&2
  exit 1
fi

BASE_DOMAIN="${HOST_IP//./-}.sslip.io"
printf "BASE_DOMAIN=%s\n" "$BASE_DOMAIN" | tee "$BASE_DOMAIN_FILE" >/dev/null
echo "$BASE_DOMAIN"
