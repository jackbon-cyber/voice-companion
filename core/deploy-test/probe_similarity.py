"""部署实测：定位"存进去了但召不回"的原因。

实测现象：第一轮说"我妈妈叫李芳，她对芒果过敏"→ 云端回复"我记得，…"，
引用了刚写入的记忆 ID；紧接着问"我妈妈有什么过敏的东西吗？"
→ 云端回复"我这边还没有关于这件事的记录"，引用为空。

两种可能：
  A. 检索根本没命中（召不回这条记忆）；
  B. 召回了，但相关性阈值把它挡掉了。

这两种的修法完全不同，必须分开。
做法：直接调嵌入服务拿两条文本的向量，算余弦相似度，
再和 MemoryRelevancePolicy 的阈值 0.476 对照。
"""

from __future__ import annotations

import json
import urllib.request

EMBED_URL = "http://127.0.0.1:8766/v1/embeddings"
MODEL = "bge-small-zh-v1.5"

# MemoryRelevancePolicy 的阈值（score = 1/(1+distance) >= 0.476）
MIN_RELEVANCE_SCORE = 0.476

FACT = "我妈妈叫李芳，她对芒果过敏"
QUESTION = "我妈妈有什么过敏的东西吗？"


def embed(text: str) -> list[float]:
    payload = json.dumps({"model": MODEL, "input": text}).encode("utf-8")
    request = urllib.request.Request(
        EMBED_URL, data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read())
    return body["data"][0]["embedding"]


def cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    norm_left = sum(a * a for a in left) ** 0.5
    norm_right = sum(b * b for b in right) ** 0.5
    return dot / (norm_left * norm_right)


def main() -> None:
    print("=== 部署实测：召不回的原因定位 ===")
    print()

    fact_vector = embed(FACT)
    question_vector = embed(QUESTION)

    similarity = cosine(fact_vector, question_vector)
    # Chroma 用平方 L2：单位向量下 squared_L2 = 2 - 2*cos
    squared_l2 = 2.0 - 2.0 * similarity
    score = 1.0 / (1.0 + squared_l2)

    print(f"陈述句向量维度：{len(fact_vector)}")
    print(f"余弦相似度：{similarity:.4f}")
    print(f"平方 L2 距离：{squared_l2:.4f}")
    print(f"换算得分（1/(1+distance)）：{score:.4f}")
    print(f"相关性阈值：{MIN_RELEVANCE_SCORE:.4f}")
    print()

    if score >= MIN_RELEVANCE_SCORE:
        print("✓ 相似度足以通过阈值 —— 召不回的原因不是阈值")
        print("  → 需要查检索侧：查询是否真命中、作用域过滤是否把结果滤掉了")
    else:
        print("★ 相似度低于阈值 —— 会被相关性闸门挡掉")
        print("  → 这就是召不回的直接原因：内存召回正确，但问法与记法差异太大")


if __name__ == "__main__":
    main()
