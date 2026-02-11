#!/usr/bin/env bash
set -euo pipefail

BASE_DOMAIN_FILE="${BASE_DOMAIN_FILE:-.env}"
rm -f "$BASE_DOMAIN_FILE"
