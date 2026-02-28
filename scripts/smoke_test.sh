#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8000}"

echo "Running DocumentWho smoke test against ${BASE_URL}"
echo

echo "[1/4] Search"
curl -s "${BASE_URL}/search?q=Aurora&top_k=5"
echo
echo

echo "[2/4] Facets"
curl -s "${BASE_URL}/facets"
echo
echo

DOC_ID="$(curl -s "${BASE_URL}/documents" | python3 - <<'PY'
import json, sys
payload = json.load(sys.stdin)
documents = payload.get("documents", [])
print(documents[0]["doc_id"] if documents else "")
PY
)"

if [[ -z "${DOC_ID}" ]]; then
  echo "No document ID returned from /documents" >&2
  exit 1
fi

echo "[3/4] Document detail for ${DOC_ID}"
curl -s "${BASE_URL}/documents/${DOC_ID}"
echo
echo

echo "[4/4] Document graph for ${DOC_ID}"
curl -s "${BASE_URL}/graph/doc/${DOC_ID}"
echo
