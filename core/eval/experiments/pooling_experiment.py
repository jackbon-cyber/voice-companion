"""一次性实验：比较 CLS 池化与均值池化对记忆召回 Top-1 的影响。

只用评测集里的 13 条样本，候选文档就是 evaluation 作用域里的 13 条记忆原文。
两种池化各自独立计算向量与排序，直接比 Top-1 命中数。
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
    url = f"{CHROMA_BASE}/{collection_id}/get"
    where = {"$and": [
        {"scope_tenant": {"$eq": "evaluation"}},
        {"scope_owner": {"$eq": "evaluation"}},
    ]}
    result = post(url, {"where": where, "include": ["documents"], "limit": 100})
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


def evaluate(label: str, queries: list[str], docs: list[str], expectations: list[str]) -> None:
    q_vectors = embed_all(queries, label)
    d_vectors = embed_all(docs, label)
    similarity = q_vectors @ d_vectors.T

    top1 = 0
    in_k = 0
    for index, expected in enumerate(expectations):
        order = np.argsort(similarity[index])[::-1]
        ranked = [docs[position] for position in order]
        top1 += ranked[0] == expected
        in_k += expected in ranked[:6]

    total = len(expectations)
    print(f"{label:>6}: Top-1={top1}/{total}={top1 / total * 100:.1f}%  "
          f"Recall@6={in_k}/{total}={in_k / total * 100:.1f}%")


def main() -> int:
    samples = load_samples()
    documents = load_documents()
    queries = [query for query, _ in samples]
    expectations = [expected for _, expected in samples]

    for pooling in ("cls", "mean"):
        evaluate(pooling, queries, documents, expectations)
    return 0


if __name__ == "__main__":
    sys.exit(main())
