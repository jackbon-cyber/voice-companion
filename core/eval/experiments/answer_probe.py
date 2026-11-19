"""测量记忆作答维度的失败样本。

这个脚本回答两个具体问题：

1. **"我接下来有什么安排" 为什么答错** —— 排第一的那条是什么？距离多少？
2. **"我有什么饮食禁忌吗" 为什么被拒答** —— 距离多少？差多少才够？

跑法（在仓库根目录）：
    F:\\tools\\python313\\python.exe core\\eval\\experiments\\answer_probe.py
"""

from __future__ import annotations

import json
import urllib.request

import numpy as np

CHROMA_BASE = "http://127.0.0.1:8765"
EMBEDDING_BASE = "http://127.0.0.1:8766"

# 评测语料（与 core/eval/memory_answer-eval.txt 的记忆原文一致）。
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

# 评测问句 → 期望的记忆原文。
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

# 相关性下限对应的距离上限。score = 1 / (1 + distance)，MIN_RELEVANCE_SCORE = 0.476。
MIN_RELEVANCE_SCORE = 0.476
CUTOFF_DISTANCE = 1.0 / MIN_RELEVANCE_SCORE - 1.0


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


def main() -> None:
    """跑一遍并打印每条问句的排序结果。"""
    corpus_vectors = [normalized(np.array(v)) for v in embed(CORPUS)]
    query_vectors = [normalized(np.array(v)) for v in embed([q for q, _ in QUERIES])]

    print(f"相关性下限 score={MIN_RELEVANCE_SCORE} 对应距离上限 {CUTOFF_DISTANCE:.4f}")
    print()

    wrong_count = 0
    refused_count = 0
    for (query, expected), query_vector in zip(QUERIES, query_vectors):
        distances = []
        for corpus_vector in corpus_vectors:
            # Chroma 默认的距离是单位向量上的平方 L2，等于 2 - 2*余弦。
            distances.append(float(2.0 - 2.0 * np.dot(query_vector, corpus_vector)))
        order = np.argsort(distances)

        top_index = int(order[0])
        top_content = CORPUS[top_index]
        top_distance = distances[top_index]
        top_score = 1.0 / (1.0 + top_distance)

        expected_index = CORPUS.index(expected)
        expected_distance = distances[expected_index]
        expected_score = 1.0 / (1.0 + expected_distance)

        status = "OK"
        if top_content != expected:
            status = "WRONG" if top_score >= MIN_RELEVANCE_SCORE else "REFUSED"
            if status == "WRONG":
                wrong_count += 1
            else:
                refused_count += 1

        print(f"[{status}] {query}")
        print(f"    期望: {expected}  距离={expected_distance:.4f} 得分={expected_score:.4f}")
        print(f"    实际: {top_content}  距离={top_distance:.4f} 得分={top_score:.4f}")
        if top_content != expected:
            print(f"    差距: 期望排名 #{list(order).index(expected_index) + 1}")
        print()

    print(f"答错 {wrong_count} 条，被拒答 {refused_count} 条，共 {len(QUERIES)} 条")
    if refused_count:
        print(f"→ 作答准确率（只算作答的）= {(len(QUERIES) - wrong_count - refused_count)}"
              f"/{len(QUERIES) - refused_count} = "
              f"{(len(QUERIES) - wrong_count - refused_count) / (len(QUERIES) - refused_count):.4f}")
        print(f"→ 作答率 = {len(QUERIES) - refused_count}/{len(QUERIES)} = "
              f"{(len(QUERIES) - refused_count) / len(QUERIES):.4f}")


if __name__ == "__main__":
    main()
