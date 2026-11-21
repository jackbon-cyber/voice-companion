"""核对关键语料在新旧阈值下的得分（排查阈值回归用）。

用法：
    F:\\tools\\python313\\python.exe core\\eval\\experiments\\check_threshold_regression.py
"""

from __future__ import annotations

import json
import urllib.request

EMBEDDING_URL = "http://127.0.0.1:8766/embeddings"

OLD_THRESHOLD = 0.529
NEW_THRESHOLD = 0.544

# 端到端隔离测试用到的关键语料。
PAIRS = [
    ("我妈妈叫什么", "我妈妈叫李芳"),
    ("我最喜欢吃什么", "我最喜欢吃红烧肉"),
    ("我妈妈叫什么", "我妈妈叫李芳，她很爱我，每天都给我做饭，还总提醒我早点休息"),
]


def embed(text: str) -> list[float]:
    """取一条文本的嵌入向量。

    @param text 文本
    @return 向量
    """
    request = urllib.request.Request(
        EMBEDDING_URL,
        data=json.dumps({"model": "bge-small-zh", "input": [text]}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload["data"][0]["embedding"]


def main() -> int:
    """输出每对语料在两个阈值下的判定。"""
    for question, memory in PAIRS:
        query_vector = embed(question)
        memory_vector = embed(memory)
        distance = sum((a - b) ** 2 for a, b in zip(query_vector, memory_vector))
        score = 1 / (1 + distance)
        old = "通过" if score >= OLD_THRESHOLD else "拒绝"
        new = "通过" if score >= NEW_THRESHOLD else "拒绝"
        flag = "  <-- 回归" if old == "通过" and new == "拒绝" else ""
        print(f"{question} -> {memory}")
        print(f"   得分 {score:.4f}   旧阈值 {OLD_THRESHOLD}: {old}   新阈值 {NEW_THRESHOLD}: {new}{flag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
