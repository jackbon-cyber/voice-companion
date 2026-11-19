"""核对"正在跑的嵌入服务"与"本地现算的向量"是不是同一个口径。

为什么需要这个核对
------------------
机器上有多个嵌入服务进程占着同一个端口（历史遗留），
而池化方式（CLS / 均值）改过一次。若某个进程是改动前启动的，
它就会给出**另一种口径**的向量 —— 表现为：

- 同一个问题，不同时间问，检索结果可能不一样；
- 本地脚本算出的阈值与服务实际使用的阈值对不上。

这类"口径漂移"极难定位：功能看起来是好的，只是数字对不上。
所以这里做一次**逐位比对**：本地按两种池化各算一遍，
与服务返回的向量比余弦相似度，一眼就能看出服务在用哪一种。

跑法（在仓库根目录）：
    F:\\tools\\python313\\python.exe core\\eval\\experiments\\verify_pooling.py
"""

from __future__ import annotations

import json
import urllib.request

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

MODEL_DIR = "core/models/embedding"
EMBEDDING_BASE = "http://127.0.0.1:8766"

PROBES = [
    "我妈妈叫李芳",
    "我最喜欢吃红烧肉",
    "我奶奶住在苏州",
]


def service_embedding(text: str) -> list[float]:
    """取服务端返回的向量。"""
    payload = json.dumps({"input": [text]}).encode("utf-8")
    request = urllib.request.Request(
        f"{EMBEDDING_BASE}/v1/embeddings",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = json.loads(response.read().decode("utf-8"))
    return body["data"][0]["embedding"]


def local_embeddings(text: str) -> tuple[np.ndarray, np.ndarray]:
    """本地按两种池化各算一遍向量。"""
    tokenizer = Tokenizer.from_file(f"{MODEL_DIR}/tokenizer.json")
    session = ort.InferenceSession(f"{MODEL_DIR}/model.onnx", providers=["CPUExecutionProvider"])

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
    return hidden[0], hidden.mean(axis=0)


def normalize(vector: np.ndarray) -> np.ndarray:
    """L2 归一化。"""
    norm = np.linalg.norm(vector)
    return vector / norm if norm > 0 else vector


def main() -> None:
    """比对服务与本地的池化口径。"""
    for probe in PROBES:
        service = normalize(np.array(service_embedding(probe)))
        cls_vector, mean_vector = local_embeddings(probe)

        cls_cosine = float(np.dot(service, normalize(cls_vector)))
        mean_cosine = float(np.dot(service, normalize(mean_vector)))

        if mean_cosine > 0.9999:
            verdict = "均值池化"
        elif cls_cosine > 0.9999:
            verdict = "CLS 池化"
        else:
            verdict = "**口径不一致**"

        print(f"{probe}")
        print(f"    与本地 CLS  的余弦 = {cls_cosine:.6f}")
        print(f"    与本地 均值 的余弦 = {mean_cosine:.6f}")
        print(f"    => 服务当前使用：{verdict}")
        print()


if __name__ == "__main__":
    main()
