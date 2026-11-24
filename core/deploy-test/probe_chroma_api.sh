#!/bin/bash
# 探测 Chroma v2 的端点契约 —— GET/POST 各自接受哪些方法。
# 之前用 urllib 试 GET/POST 来回猜，浪费时间；直接探测一次问清楚。

BASE="http://127.0.0.1:8765/api/v2/tenants/default_tenant/databases/default_database/collections"
ID=$(curl -s "$BASE" | python3 -c "import sys,json; print(json.load(sys.stdin)[0]['id'])")
echo "collection id = $ID"

echo "--- count ---"
curl -s -o /dev/null -w 'GET  %{http_code}\n' "$BASE/$ID/count"
curl -s -o /dev/null -w 'POST %{http_code}\n' -X POST -H 'Content-Type: application/json' -d '{}' "$BASE/$ID/count"

echo "--- get ---"
curl -s -o /dev/null -w 'GET  %{http_code}\n' "$BASE/$ID/get"
echo "--- get (POST) body ---"
curl -s -X POST -H 'Content-Type: application/json' -d '{"include":["documents","metadatas"]}' "$BASE/$ID/get" | head -c 700
echo
echo "--- query (POST) ---"
curl -s -X POST -H 'Content-Type: application/json' \
  -d '{"query_embeddings":[[0.01,0.02]],"n_results":1}' \
  "$BASE/$ID/query" | head -c 300
