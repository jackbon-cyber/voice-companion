"""测量记忆作答维度的排名、得分与"领先幅度"。

这个脚本回答三个问题：

1. Chroma 返回的距离与本地算的是不是同一个口径；
2. 每条问句排第一的那条与第二条的得分差有多大；
3. "领先幅度"能不能把"答错/该拒答"与"答对"区分开。

跑法（在仓库根目录）：
    F:\\tools\\python313\\python.exe core\\eval\\experiments\\margin_probe.py
"""

from __future__ import annotations

import json
import urllib.request

import numpy as np

CHROMA_BASE = "http://127.0.0.1:8765"
EMBEDDING_BASE = "http://127.0.0.1:8766"

MIN_RELEVANCE_SCORE = 0.476

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


def embed(texts: list[str]) -> list[list[float]]:
    """调用本地嵌入服务取向量。"""
    payload = json.dumps({"input": texts}).encode("utf-8")
    request = urllib.request.Request(
        f"{EMBEDDING_BASE}/v1/embeddings",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        body = json.loads(response.read().decode("utf-8"))
    return [item["embedding"] for item in body["data"]]


def normalized(vector: np.ndarray) -> np.ndarray:
    """L2 归一化。"""
    norm = np.linalg.norm(vector)
    return vector / norm if norm > 0 else vector


def chroma_query(collection: str, embedding: list[float], top_k: int) -> list[tuple[str, float]]:
    """向 Chroma 发一次查询，返回 (文档, 距离) 列表。"""
    url = (
        f"{CHROMA_BASE}/api/v2/tenants/default_tenant/databases/default_database"
        f"/collections/{collection}/query"
    )
    payload = json.dumps({
        "query_embeddings": [embedding],
        "n_results": top_k,
        "include": ["documents", "metadatas", "distances"],
    }).encode("utf-8")
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        body = json.loads(response.read().decode("utf-8"))

    documents = body["documents"][0]
    distances = body["distances"][0]
    return list(zip(documents, distances))


def main() -> None:
    """跑一遍并打印排名、得分、领先幅度。"""
    corpus_vectors = [normalized(np.array(v)) for v in embed(CORPUS)]
    query_vectors = [normalized(np.array(v)) for v in embed([q for q, _ in QUERIES])]

    correct_margins: list[float] = []
    wrong_margins: list[float] = []

    for (query, expected), query_vector in zip(QUERIES, query_vectors):
        distances = []
        for corpus_vector in corpus_vectors:
            distances.append(float(2.0 - 2.0 * np.dot(query_vector, corpus_vector)))
        order = np.argsort(distances)

        top_index = int(order[0])
        top_content = CORPUS[top_index]
        top_distance = distances[top_index]
        top_score = 1.0 / (1.0 + top_distance)

        second_index = int(order[1]) if len(order) > 1 else top_index
        second_score = 1.0 / (1.0 + distances[second_index])
        margin = top_score - second_score

        is_correct = top_content == expected
        status = "OK" if is_correct else ("WRONG" if top_score >= MIN_RELEVANCE_SCORE
                                           else "REFUSED")

        expected_index = CORPUS.index(expected)
        expected_score = 1.0 / (1.0 + distances[expected_index])

        print(f"[{status}] {query}")
        print(f"    期望 {expected} 得分={expected_score:.4f}")
        print(f"    第一 {top_content} 得分={top_score:.4f}  领先={margin:+.4f}")
        print(f"    第二 {CORPUS[second_index]} 得分={second_score:.4f}")
        print()

        if is_correct:
            correct_margins.append(margin)
        else:
            wrong_margins.append(margin)

    print("答对的领先幅度：", [f"{m:+.4f}" for m in correct_margins])
    print("答错/拒答的领先幅度：", [f"{m:+.4f}" for m in wrong_margins])
    if correct_margins:
        print(f"答对的最小领先幅度 = {min(correct_margins):+.4f}")
    if wrong_margins:
        print(f"答错的最大领先幅度 = {max(wrong_margins):+.4f}")

    # 用真实 Chroma 校验距离口径。
    print()
    print("=== 用真实 Chroma 校验口径 ===")
    for query, _ in QUERIES[:3]:
        embedding = embed([query])[0]
        try:
            hits = chroma_query("mem_longterm", embedding, 3)
        except Exception as error:  # noqa: BLE001 - 探测性脚本
            print(f"  Chroma 查询失败（评测作用域可能尚未写入）：{error}")
            break
        print(f"  {query}")
        for document, distance in hits:
            print(f"    {document}  距离={distance:.4f}  得分={1.0 / (1.0 + distance):.4f}")


if __name__ == "__main__":
    main()
