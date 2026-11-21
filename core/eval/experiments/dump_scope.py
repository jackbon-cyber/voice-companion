"""列出记忆集合中指定作用域的记录（排查召回失败用）。

用法：
    F:\\tools\\python313\\python.exe core\\eval\\experiments\\dump_scope.py <scope_owner>
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
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    """输出指定作用域的记录。"""
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    owner = sys.argv[1]
    collections = json.loads(urllib.request.urlopen(BASE, timeout=10).read())
    collection_id = next(c["id"] for c in collections if c.get("name") == "mem_longterm")

    data = post(
        f"{BASE}/{collection_id}/get",
        {
            "limit": 50,
            "where": {"scope_owner": {"$eq": owner}},
            "include": ["documents", "metadatas"],
        },
    )

    documents = data.get("documents", [])
    metadatas = data.get("metadatas", [])
    print(f"作用域 {owner} 共 {len(documents)} 条")
    for index, document in enumerate(documents):
        metadata = metadatas[index] if index < len(metadatas) else {}
        parent = metadata.get("parent_id", "-")
        print(f"  文档：{document}")
        print(f"  父id：{parent}  归档：{metadata.get('archived')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
