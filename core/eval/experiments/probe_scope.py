"""直接查询某个作用域的召回结果（排查召回失败用）。

用法：
    F:\\tools\\python313\\python.exe core\\eval\\experiments\\probe_scope.py <scope_owner> <问句>
"""

from __future__ import annotations

import json
import sys
import urllib.request

BASE = (
    "http://127.0.0.1:8765/api/v2/tenants/default_tenant"
    "/databases/default_database/collections"
)


def post(url: str, payload: dict) -> dict:
    """发起 POST 请求。

    @param url 地址
    @param payload 请求体
    @return 响应内容
    """
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    """查询并打印召回结果。"""
    if len(sys.argv) < 3:
        print(__doc__)
        return 2

    owner = sys.argv[1]
    question = sys.argv[2]

    collections = json.loads(urllib.request.urlopen(BASE, timeout=10).read())
    collection_id = next(c["id"] for c in collections if c.get("name") == "mem_longterm")

    embed = post(
        "http://127.0.0.1:8766/embeddings",
        {"model": "bge-small-zh", "input": [question]},
    )
    vector = embed["data"][0]["embedding"]

    where = {
        "$and": [
            {"scope_tenant": {"$eq": "default"}},
            {"scope_owner": {"$eq": owner}},
            {"archived": {"$eq": False}},
        ]
    }
    result = post(
        f"{BASE}/{collection_id}/query",
        {
            "query_embeddings": [vector],
            "n_results": 5,
            "where": where,
            "include": ["documents", "distances", "metadatas"],
        },
    )

    print(f"作用域 {owner}   问句 {question!r}")
    documents = result.get("documents", [[]])[0]
    distances = result.get("distances", [[]])[0]
    metadatas = result.get("metadatas", [[]])[0]
    for index, document in enumerate(documents):
        distance = distances[index]
        metadata = metadatas[index]
        print(
            f"   dist={distance:.4f} score={1 / (1 + distance):.4f}  "
            f"parent={str(metadata.get('parent_id', '-'))[:8]}  {document}"
        )
    if not documents:
        print("   （无命中）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
