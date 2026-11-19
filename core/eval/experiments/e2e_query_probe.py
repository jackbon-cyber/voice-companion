"""检查相关性下限对**端到端断言**的影响。

为什么必须单独检查
------------------
相关性下限是"低于它就拒答"。它一旦调高，最先被拒答的
往往是**端到端断言依赖的那几条** —— 端到端脚本要断言
"用户 A 的回复引用自己的记忆"，如果那条被拒答了，
断言会以"引用来源为空"的形式失败，而排查方向会被带偏
（看起来像隔离失效，其实是阈值问题）。

这个脚本把端到端用到的问句与记忆原文放在真实 Chroma 上量一遍，
回答两件事：

1. 端到端的关键问句在新下限下**还能不能被作答**；
2. 改写说法（同一事实的另一种说法）**会不会被误拒**。

跑法（在仓库根目录）：
    F:\\tools\\python313\\python.exe data\\e2e_query_probe.py
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

CHROMA_BASE = "http://127.0.0.1:8765"
EMBEDDING_BASE = "http://127.0.0.1:8766"

TENANT = "default_tenant"
DATABASE = "default_database"
COLLECTION = "mem_longterm"
SCOPE_TENANT = "default"
SCOPE_OWNER = "e2e-query-probe"

# 端到端脚本实际使用的问句与记忆原文。
E2E_PAIRS = [
    ("我妈妈叫李芳", "我妈妈叫什么"),
    ("我最喜欢吃红烧肉", "我最喜欢吃什么"),
]

# 记忆原文 → 改写说法。用于检查"改写会不会被误拒"。
PARAPHRASES = [
    ("我妈妈叫李芳", "我妈妈的名字是李芳"),
    ("我最喜欢吃红烧肉", "我最爱吃的菜是红烧肉"),
]


def request_json(url: str, payload: dict | None = None, method: str = "POST") -> object:
    """发起一次 JSON 请求。"""
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"HTTP {error.code}: {error.read().decode('utf-8')}") from error
    return json.loads(body) if body else None


def embed(texts: list[str]) -> list[list[float]]:
    """调用本地嵌入服务取向量。"""
    body = request_json(f"{EMBEDDING_BASE}/v1/embeddings", {"input": texts})
    return [item["embedding"] for item in body["data"]]


def collections_url() -> str:
    """返回集合列表地址。"""
    return f"{CHROMA_BASE}/api/v2/tenants/{TENANT}/databases/{DATABASE}/collections"


def resolve_collection_id() -> str:
    """查出集合 id。"""
    for item in request_json(collections_url(), method="GET"):
        if item.get("name") == COLLECTION:
            return item["id"]
    raise RuntimeError(f"集合不存在：{COLLECTION}")


def scope_where() -> dict:
    """返回作用域过滤条件。"""
    return {
        "$and": [
            {"scope_tenant": {"$eq": SCOPE_TENANT}},
            {"scope_owner": {"$eq": SCOPE_OWNER}},
        ]
    }


def reset_scope(collection_id: str) -> None:
    """清空本脚本的作用域。"""
    request_json(
        f"{collections_url()}/{collection_id}/delete", {"where": scope_where()}
    )


def write_corpus(collection_id: str, corpus: list[str]) -> None:
    """把语料写入记忆库。"""
    vectors = embed(corpus)
    request_json(
        f"{collections_url()}/{collection_id}/add",
        {
            "ids": [f"e2eprobe-{index}" for index in range(len(corpus))],
            "embeddings": vectors,
            "documents": corpus,
            "metadatas": [
                {
                    "scope_tenant": SCOPE_TENANT,
                    "scope_owner": SCOPE_OWNER,
                    "weight": 1.0,
                    "created_at": 1_000_000 + index,
                    "archived": False,
                }
                for index in range(len(corpus))
            ],
        },
    )


def query(collection_id: str, text: str, top_k: int = 3) -> list[tuple[str, float]]:
    """查询记忆库，返回 (文档, 距离) 列表。"""
    vector = embed([text])[0]
    body = request_json(
        f"{collections_url()}/{collection_id}/query",
        {
            "query_embeddings": [vector],
            "n_results": top_k,
            "include": ["documents", "distances"],
            "where": scope_where(),
        },
    )
    return list(zip(body["documents"][0], body["distances"][0]))


def main() -> None:
    """测量端到端关键问句与改写问句的得分。"""
    collection_id = resolve_collection_id()
    reset_scope(collection_id)

    corpus = [original for original, _ in E2E_PAIRS]
    write_corpus(collection_id, corpus)

    print("=== 端到端关键问句 ===")
    for original, question in E2E_PAIRS:
        hits = query(collection_id, question)
        top_document, distance = hits[0]
        score = 1.0 / (1.0 + distance)
        match = "OK " if top_document == original else "!! "
        print(f"{match}{question}")
        print(f"    期望 {original}  实际 {top_document}")
        print(f"    得分={score:.4f}  距离={distance:.4f}")
        for document, other_distance in hits[1:]:
            other_score = 1.0 / (1.0 + other_distance)
            print(f"    第二 {document}  得分={other_score:.4f}")
        print()

    print("=== 改写说法（同一事实的另一种说法）===")
    for original, rewrite in PARAPHRASES:
        hits = query(collection_id, rewrite)
        top_document, distance = hits[0]
        score = 1.0 / (1.0 + distance)
        match = "OK " if top_document == original else "!! "
        print(f"{match}{rewrite}")
        print(f"    期望 {original}  实际 {top_document}  得分={score:.4f}")
        print()

    reset_scope(collection_id)


if __name__ == "__main__":
    main()
