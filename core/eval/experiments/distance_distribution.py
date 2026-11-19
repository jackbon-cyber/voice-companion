"""一次性实验：测量评测问句与记忆库全量记录的距离分布。

用途：为"相关性下限"（低于此距离即视为不相关）给出实测依据，
而不是拍一个数字。

数据来源：
- 13 条评测问句（core/eval/memory_recall-eval.txt 的第二段）
- 记忆库 evaluation 作用域下的 13 条记忆原文（评测时预先写入的原文）
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
    where = {"$and": [
        {"scope_tenant": {"$eq": "evaluation"}},
        {"scope_owner": {"$eq": "evaluation"}},
    ]}
    result = post(
        f"{CHROMA_BASE}/{collection_id}/get",
        {"where": where, "include": ["documents"], "limit": 100},
    )
    return result["documents"]


def embed_all(texts: list[str]) -> np.ndarray:
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
        vector = hidden[0]
        norm = float(np.linalg.norm(vector))
        vectors.append(vector / norm if norm > 0 else vector)
    return np.array(vectors)


def main() -> int:
    samples = load_samples()
    documents = load_documents()
    queries = [query for query, _ in samples]
    expectations = [expected for _, expected in samples]

    q_vectors = embed_all(queries)
    d_vectors = embed_all(documents)
    # Chroma 的 /query 返回平方 L2；单位向量下 squared_L2 = 2 - 2*cos
    distances = 2.0 - 2.0 * (q_vectors @ d_vectors.T)

    matched = []
    unmatched = []
    for row, expected in enumerate(expectations):
        for column, document in enumerate(documents):
            value = float(distances[row][column])
            if document == expected:
                matched.append((value, queries[row], document))
            else:
                unmatched.append((value, queries[row], document))

    matched.sort()
    unmatched.sort()

    print(f"相关对（问句 ↔ 其记忆原文）共 {len(matched)} 个")
    print(f"  最小 {matched[0][0]:.4f}   最大 {matched[-1][0]:.4f}")
    print(f"不相关对（问句 ↔ 其它记忆）共 {len(unmatched)} 个")
    print(f"  最小 {unmatched[0][0]:.4f}   最大 {unmatched[-1][0]:.4f}")

    print()
    print("相关对按距离升序：")
    for value, query, document in matched:
        print(f"  {value:.4f}  {query}  →  {document}")

    print()
    print("不相关对中最小的 12 个（这些是距离下限的真实边界）：")
    for value, query, document in unmatched[:12]:
        print(f"  {value:.4f}  {query}  ✗  {document}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
