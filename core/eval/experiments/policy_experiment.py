"""一次性实验：验证「均值池化 + 相关性下限 + 排序余量」对记忆回答质量的影响。

背景
----
当前实现的三个问题：

1. 嵌入服务用 CLS 池化，注释称"实测 CLS 判别力优于均值池化" ——
   但那是**意图原型分类**场景的结论，记忆召回场景未必成立。
2. 记忆召回维度只测 Recall@K（正确答案是否出现在前 K 条），
   而产品真正回复用户的是**排序第一**那条。
3. 回复无条件把排序第一条当事实陈述，不判断它是否真的相关。

本实验在**同一批 13 条评测问句**上比较：

- 池化方式：CLS vs 均值
- 策略：无策略 / 仅相关性下限 / 相关性下限 + 排序余量

输出：作答覆盖率、作答正确率、整体正确率（拒答不计分）。
"""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
EMBEDDING_DIR = REPO_ROOT / "core" / "models" / "embedding"

CHROMA_BASE = (
    "http://127.0.0.1:8765/api/v2/tenants/default_tenant/databases/default_database/collections"
)

# 距离 = 平方 L2 = 2 - 2*cos（单位向量），落在 [0, 4]。
DISTANCE_FLOORS = (0.90, 1.00, 1.10, 1.20)
MARGINS = (0.00, 0.05, 0.10)


def post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return json.load(urllib.request.urlopen(req))


def load_samples() -> list[tuple[str, str]]:
    samples: list[tuple[str, str]] = []
    with open(REPO_ROOT / "core" / "eval" / "memory_recall-eval.txt", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            parts = line.split("|")
            samples.append((parts[1], parts[3]))
    return samples


def load_documents() -> list[str]:
    data = json.load(urllib.request.urlopen(CHROMA_BASE))
    collection_id = [c["id"] for c in data if c["name"] == "mem_longterm"][0]
    where = {"$and": [
        {"scope_tenant": {"$eq": "evaluation"}},
        {"scope_owner": {"$eq": "evaluation"}},
    ]}
    result = post(
        f"{CHROMA_BASE}/{collection_id}/get",
        {"where": where, "include": ["documents"], "limit": 100},
    )
    return result["documents"]


def embed_all(texts: list[str], pooling: str) -> np.ndarray:
    import onnxruntime as ort
    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_file(str(EMBEDDING_DIR / "tokenizer.json"))
    session = ort.InferenceSession(
        str(EMBEDDING_DIR / "model.onnx"), providers=["CPUExecutionProvider"]
    )
    vectors = []
    for text in texts:
        encoding = tokenizer.encode(text)
        input_ids = np.array([encoding.ids], dtype=np.int64)
        attention_mask = np.ones_like(input_ids)
        outputs = session.run(
            None,
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "token_type_ids": np.zeros_like(input_ids),
            },
        )
        hidden = outputs[0][0]
        vector = hidden[0] if pooling == "cls" else hidden.mean(axis=0)
        norm = float(np.linalg.norm(vector))
        vectors.append(vector / norm if norm > 0 else vector)
    return np.array(vectors)


def main() -> int:
    samples = load_samples()
    documents = load_documents()
    queries = [query for query, _ in samples]
    expectations = [expected for _, expected in samples]
    total = len(samples)

    for pooling in ("cls", "mean"):
        q_vectors = embed_all(queries, pooling)
        d_vectors = embed_all(documents, pooling)
        distances = 2.0 - 2.0 * (q_vectors @ d_vectors.T)

        rankings = []
        for row in range(total):
            order = np.argsort(distances[row])
            rankings.append([(float(distances[row][col]), documents[col]) for col in order])

        matched = []
        unmatched = []
        for rank, exp in zip(rankings, expectations):
            for distance, document in rank:
                if document == exp:
                    matched.append(distance)
                else:
                    unmatched.append(distance)
        print(f"===== 池化={pooling} =====")
        print(f"  相关对距离 max={max(matched):.4f}   不相关对距离 min={unmatched[0]:.4f}")
        print(f"  无策略：作答 {total}，答对 "
              f"{sum(1 for rank, exp in zip(rankings, expectations) if rank[0][1] == exp)}"
              f" -> 整体正确率 "
              f"{sum(1 for rank, exp in zip(rankings, expectations) if rank[0][1] == exp) / total * 100:.1f}%")

        for floor in DISTANCE_FLOORS:
            for margin in MARGINS:
                answered = 0
                correct = 0
                for rank, exp in zip(rankings, expectations):
                    top1_distance, top1_doc = rank[0]
                    top2_distance = rank[1][0] if len(rank) > 1 else float("inf")
                    if top1_distance > floor or (top2_distance - top1_distance) < margin:
                        continue
                    answered += 1
                    correct += top1_doc == exp
                print(
                    f"  floor={floor:.2f} margin={margin:.2f}: "
                    f"作答 {answered}/{total}，答对 {correct}，"
                    f"作答正确率 {correct / answered * 100 if answered else 0:.1f}%，"
                    f"整体正确率 {correct / total * 100:.1f}%"
                )
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
