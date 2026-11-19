"""在**带得分的记忆库**上评估"相关性下限"这一条策略。

为什么要在真实 Chroma 上评估
------------------------------
之前用本地算出来的距离做的实验，有一处隐患：
本地算的是"余弦距离"，而 Chroma 返回的是**平方 L2**。
两者虽然单调对应，但换算成得分后数值可能对不上，
阈值也就对不上。这个脚本直接查真实 Chroma，用**它返回的距离**做判定，
消除这层不确定性。

被评估的策略
------------
**只有相关性下限**（不做区分度判定）。

为什么先只测这一条
------------------
记忆作答维度里现在有 1 条答错（"我接下来有什么安排"问成了"正在准备考研"）。
修它有两条路：

- **加区分度阈值**（排第一与排第二的得分差太小就拒答）；
- **调相关性下限**（把这条整体拒答掉）。

哪条更好，不能靠感觉 —— 要看两条路分别会让多少条样本变成拒答。
拒答不是失败，但**拒答太多就是产品没用**。
所以这里把两条路都量一遍，用数据来选。

跑法（在仓库根目录）：
    F:\\tools\\python313\\python.exe core\\eval\\experiments\\policy_on_chroma.py
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
SCOPE_OWNER = "policy-probe"

# 评测语料：记忆原文与问句（与 core/eval/memory_answer-eval.txt 一致）。
CORPUS = [
    "我奶奶住在苏州",
    "我养了三只仓鼠",
    "我最爱吃酸菜鱼",
    "我下个月要参加同学的婚礼",
    "我怕黑",
    "我习惯用左手写字",
    "我表姐在南京工作",
    "我今年三十五岁",
    "我每周三去健身房",
    "我对芒果过敏",
    "我岳父喜欢下棋",
    "我的车是白色的",
    "我正在准备考研",
]

QUERIES = [
    ("我奶奶家在哪里", "我奶奶住在苏州"),
    ("我家养了几只小动物", "我养了三只仓鼠"),
    ("我最爱的菜是什么", "我最爱吃酸菜鱼"),
    ("我接下来有什么安排", "我下个月要参加同学的婚礼"),
    ("我有什么害怕的东西吗", "我怕黑"),
    ("我写字用什么手", "我习惯用左手写字"),
    ("我表姐在哪个城市工作", "我表姐在南京工作"),
    ("我的年龄是多少", "我今年三十五岁"),
    ("我一般什么时候去健身", "我每周三去健身房"),
    ("我有什么饮食禁忌吗", "我对芒果过敏"),
    ("我岳父有什么爱好", "我岳父喜欢下棋"),
    ("我的车是什么颜色", "我的车是白色的"),
    ("我最近在忙什么", "我正在准备考研"),
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


def reset_scope(collection_id: str) -> None:
    """清空本脚本的作用域。"""
    request_json(
        f"{collections_url()}/{collection_id}/delete",
        {
            "where": {
                "$and": [
                    {"scope_tenant": {"$eq": SCOPE_TENANT}},
                    {"scope_owner": {"$eq": SCOPE_OWNER}},
                ]
            }
        },
    )


def write_corpus(collection_id: str, corpus: list[str]) -> None:
    """把语料写入记忆库。"""
    vectors = embed(corpus)
    ids = [f"policy-{index}" for index in range(len(corpus))]
    metadatas = [
        {
            "scope_tenant": SCOPE_TENANT,
            "scope_owner": SCOPE_OWNER,
            "weight": 1.0,
            "created_at": 1_000_000 + index,
            "archived": False,
        }
        for index in range(len(corpus))
    ]
    request_json(
        f"{collections_url()}/{collection_id}/add",
        {
            "ids": ids,
            "embeddings": vectors,
            "documents": corpus,
            "metadatas": metadatas,
        },
    )


def query(collection_id: str, text: str, top_k: int = 5) -> list[tuple[str, float]]:
    """查询记忆库，返回 (文档, 距离) 列表。"""
    vector = embed([text])[0]
    body = request_json(
        f"{collections_url()}/{collection_id}/query",
        {
            "query_embeddings": [vector],
            "n_results": top_k,
            "include": ["documents", "distances"],
            "where": {
                "$and": [
                    {"scope_tenant": {"$eq": SCOPE_TENANT}},
                    {"scope_owner": {"$eq": SCOPE_OWNER}},
                ]
            },
        },
    )
    return list(zip(body["documents"][0], body["distances"][0]))


def main() -> None:
    """在真实 Chroma 上评估相关性下限策略。"""
    collection_id = resolve_collection_id()
    reset_scope(collection_id)
    write_corpus(collection_id, CORPUS)

    measurements: list[tuple[str, str, str, float, float, float]] = []
    for query_text, expected in QUERIES:
        hits = query(collection_id, query_text)
        documents = [document for document, _ in hits]
        distances = [distance for _, distance in hits]
        scores = [1.0 / (1.0 + distance) for distance in distances]

        top_document = documents[0]
        top_score = scores[0]
        margin = top_score - scores[1] if len(scores) > 1 else 0.0
        expected_score = 1.0 / (1.0 + query(collection_id, expected)[0][1]) \
            if expected in documents else 0.0
        measurements.append(
            (query_text, expected, top_document, top_score, margin, expected_score)
        )

    print("=== 真实 Chroma 上的检索结果 ===")
    print(f"{'问句':<16} {'第一':<14} {'得分':>7} {'领先':>8} {'期望得分':>9}")
    for query_text, expected, top_document, top_score, margin, expected_score in measurements:
        mark = "OK " if top_document == expected else "!! "
        print(f"{mark}{query_text:<14} {top_document:<14} {top_score:>7.4f} "
              f"{margin:>+8.4f} {expected_score:>9.4f}")

    print()
    print("=== 策略对比：只用相关性下限 ===")
    print(f"{'下限':>6} {'作答':>5} {'答对':>5} {'拒答':>5} {'准确率':>8} {'覆盖率':>8}")
    for floor in [0.40, 0.45, 0.476, 0.50, 0.55, 0.60, 0.65, 0.70, 0.7311, 0.75]:
        answered = 0
        correct = 0
        for _, expected, top_document, top_score, _, _ in measurements:
            if top_score < floor:
                continue
            answered += 1
            if top_document == expected:
                correct += 1
        accuracy = correct / answered if answered else 0.0
        coverage = answered / len(measurements)
        print(f"{floor:>6.4f} {answered:>5} {correct:>5} {answered - correct:>5} "
              f"{accuracy:>8.4f} {coverage:>8.4f}")

    print()
    print("=== 策略对比：相关性下限 + 区分度下限 ===")
    print(f"{'下限':>6} {'区分度':>8} {'作答':>5} {'答对':>5} {'拒答':>5} {'准确率':>8} {'覆盖率':>8}")
    for floor in [0.40, 0.45, 0.476, 0.50]:
        for margin_floor in [0.0, 0.02, 0.03, 0.05, 0.08, 0.10]:
            answered = 0
            correct = 0
            for _, expected, top_document, top_score, margin, _ in measurements:
                if top_score < floor or margin < margin_floor:
                    continue
                answered += 1
                if top_document == expected:
                    correct += 1
            accuracy = correct / answered if answered else 0.0
            coverage = answered / len(measurements)
            print(f"{floor:>6.4f} {margin_floor:>8.3f} {answered:>5} {correct:>5} "
                  f"{answered - correct:>5} {accuracy:>8.4f} {coverage:>8.4f}")

    reset_scope(collection_id)


if __name__ == "__main__":
    main()
