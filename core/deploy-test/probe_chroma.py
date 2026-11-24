"""部署实测：直查 Chroma，看云端到底存了什么、查得到吗。

定位问题用。绕开云端，直接问 Chroma：
  1. 集合里有哪些记录、文档内容是什么；
  2. 用"提问"的向量去查，看能不能召回；
  3. 带作用域过滤查，看过滤条件是不是把结果滤掉了。

**为什么值得单独做这一步**

云端返回"我这边还没有关于这件事的记录"，有三种可能：
  * 没存进去；
  * 存进去了但查不到（向量/距离问题）；
  * 查到了但被作用域过滤滤掉了（隔离逻辑问题）。

三者的修法完全不同，且都只在部署形态下才暴露。
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request

CHROMA = "http://127.0.0.1:8765"
TENANT = "default_tenant"
DATABASE = "default_database"
EMBED = "http://127.0.0.1:8766/v1/embeddings"

QUESTION = "我妈妈有什么过敏的东西吗？"


def post(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def get(url: str) -> dict | list:
    request = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read())


def embed(text: str) -> list[float]:
    body = post(EMBED, {"model": "bge-small-zh-v1.5", "input": text})
    return body["data"][0]["embedding"]


def show_query(label: str, base: str, quoted: str, query_vector: list[float], where: dict | None) -> None:
    payload: dict = {
        "query_embeddings": [query_vector],
        "n_results": 3,
        "include": ["documents", "distances"],
    }
    if where:
        payload["where"] = where
    result = post(f"{base}/{quoted}/query", payload)
    ids = result["ids"][0]
    docs = result["documents"][0]
    dists = result["distances"][0]
    print(f"{label}：")
    if not ids:
        print("  （无结果）")
        return
    for hit_id, hit_doc, hit_dist in zip(ids, docs, dists):
        score = 1.0 / (1.0 + hit_dist)
        print(f"  {hit_id}  dist={hit_dist:.4f}  score={score:.4f}  doc={hit_doc}")


def main() -> None:
    print("=== 部署实测：直查 Chroma ===")
    print()

    base = f"{CHROMA}/api/v2/tenants/{TENANT}/databases/{DATABASE}/collections"

    listed = get(base)
    collections = listed["collections"] if isinstance(listed, dict) else listed
    if not collections:
        print("★ 没有任何集合 —— 记忆根本没落库")
        return

    collection = collections[0]
    name = collection["name"]
    # 用 collection id 而不是名字 —— id 是 UUID，稳定且无编码问题。
    quoted = collection["id"]
    print(f"集合：{name}  id={quoted}  dimension={collection.get('dimension')}")
    print(f"空间：{collection.get('configuration_json', {}).get('hnsw_configuration', {}).get('space')}")

    counted = get(f"{base}/{quoted}/count")
    count = counted["count"] if isinstance(counted, dict) else counted
    print(f"记录数：{count}")
    if count == 0:
        print("★ 集合是空的 —— 记忆写入没落库")
        return

    records = post(f"{base}/{quoted}/get", {"include": ["documents", "metadatas"]})
    docs = records.get("documents") or []
    metas = records.get("metadatas") or []
    print(f"文档内容：{docs}")
    print(f"元数据：{metas}")

    query_vector = embed(QUESTION)
    print()
    show_query(f"不带过滤查询「{QUESTION}」", base, quoted, query_vector, None)

    if metas:
        owner = metas[0].get("scope_owner")
        print()
        print(f"元数据字段：{list(metas[0].keys())}   scope_owner={owner}")
        show_query(f"带 scope_owner={owner} 过滤查询", base, quoted, query_vector, {"scope_owner": owner})


if __name__ == "__main__":
    main()
