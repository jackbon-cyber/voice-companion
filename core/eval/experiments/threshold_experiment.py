"""一次性实验：为记忆陈述准入策略确定阈值（全部基于实测，不拍脑袋）。

口径
----
* 池化：均值（本次刚改���的池化方式）
* 距离：Chroma 的平方 L2 = 2 - 2·cos（单位向量），落在 [0, 4]
* 得分：score = 1 / (1 + distance)，越大越相关

要回答的问题
------------
1. 正确记忆与错误记忆的**距离分布**是否可分？可分的话下限定在哪？
2. Top-1 答错时，第一名与第二名的**距离差**是否显著更小？
   （若是，"区分度"判据就能拦住它）
3. 加上"相关性下限 + 区分度"两道判据后，
   覆盖率与"作答正确率"分别是多少？

数据
----
13 条评测问句 × 13 条记忆原文 = 169 对，取其中 13 对为"相关"、156 对为"不相关"。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
EMBEDDING_DIR = REPO_ROOT / "core" / "models" / "embedding"


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
        vector = hidden.mean(axis=0)
        norm = float(np.linalg.norm(vector))
        vectors.append(vector / norm if norm > 0 else vector)
    return np.array(vectors)


def score_of(distance: float) -> float:
    """距离换算成得分，与 ChromaQueryResultReader.toScore 同一公式。"""
    return 1.0 / (1.0 + distance)


def main() -> int:
    samples = load_samples()
    queries = [query for query, _ in samples]
    expectations = [expected for _, expected in samples]
    documents = sorted(set(expectations))

    q_vectors = embed_all(queries)
    d_vectors = embed_all(documents)
    distances = 2.0 - 2.0 * (q_vectors @ d_vectors.T)

    total = len(queries)
    print(f"记忆条数 {len(documents)}，问句数 {total}\n")

    # ---- 1. 相关对 vs 不相关对的距离分布 ----
    relevant: list[float] = []
    irrelevant: list[float] = []
    for row, expected in enumerate(expectations):
        for col, document in enumerate(documents):
            value = float(distances[row][col])
            (relevant if document == expected else irrelevant).append(value)

    print("【1】相关对 vs 不相关对")
    print(f"  相关对   {len(relevant):3d} 对，距离 min={min(relevant):.4f} max={max(relevant):.4f}")
    print(f"  不相关对 {len(irrelevant):3d} 对，距离 min={min(irrelevant):.4f} max={max(irrelevant):.4f}")
    print(f"  => 相关对最大 {max(relevant):.4f}  {'>' if max(relevant) > min(irrelevant) else '<='}"
          f" 不相关对最小 {min(irrelevant):.4f}"
          f"  （{'完全可分' if max(relevant) <= min(irrelevant) else '存在重叠，纯阈值无法完全分开'}）")
    print(f"  得分口径：相关对最低 {score_of(max(relevant)):.4f}，"
          f"不相关对最高 {score_of(min(irrelevant)):.4f}\n")

    # ---- 2. Top-1 答对/答错时的排名结构 ----
    print("【2】逐条问句的排名结构")
    rows = []
    for row, expected in enumerate(expectations):
        order = np.argsort(distances[row])
        top1_doc = documents[order[0]]
        top1_d = float(distances[row][order[0]])
        top2_d = float(distances[row][order[1]]) if len(order) > 1 else float("inf")
        margin = top2_d - top1_d
        correct = top1_doc == expected
        rows.append((queries[row], expected, top1_doc, top1_d, top2_d, margin, correct))
        flag = "对" if correct else "错"
        print(f"  [{flag}] {queries[row]}")
        print(f"        top1={top1_doc} d={top1_d:.4f} score={score_of(top1_d):.4f} | "
              f"top2 d={top2_d:.4f} | 距离差={margin:+.4f}")

    correct_margins = [row[5] for row in rows if row[6]]
    wrong_margins = [row[5] for row in rows if not row[6]]
    print()
    print(f"  答对的 {len(correct_margins)} 条：距离差 min={min(correct_margins):.4f} "
          f"max={max(correct_margins):.4f}")
    if wrong_margins:
        print(f"  答错的 {len(wrong_margins)} 条：距离差 "
              f"{', '.join(f'{m:+.4f}' for m in wrong_margins)}")
    print()

    # ---- 3. 策略扫描 ----
    print("【3】策略扫描（相关性下限按距离给定，得分=1/(1+distance)）")
    print("  距离上限   区分度下限   作答   答对   作答正确率   覆盖率   整体正确率")
    for max_distance in (1.10, 1.15, 1.20, 1.25, 1.30, 9.99):
        for min_margin in (0.0, 0.01, 0.02, 0.05, 0.10):
            answered = 0
            correct = 0
            for row, expected, top1_doc, top1_d, top2_d, margin, _ in rows:
                if top1_d > max_distance:
                    continue
                if margin < min_margin:
                    continue
                answered += 1
                correct += top1_doc == expected
            print(f"  {max_distance:8.2f}   {min_margin:8.2f}   "
                  f"{answered:4d}   {correct:4d}   "
                  f"{(correct / answered * 100 if answered else 0):9.1f}%   "
                  f"{answered / total * 100:6.1f}%   {correct / total * 100:8.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
