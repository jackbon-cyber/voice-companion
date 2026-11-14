"""校验本地嵌入服务的语义判别力。

这是一条**需要真实模型**的集成测试：模型权重不在版本库里（22.9 MB），
因此模型缺失时整条测试跳过，而不是伪造一个通过的结果。

实测口径（2026-11 首次运行）：
    同义句余弦 0.88，无关句余弦 0.28
"""

from __future__ import annotations

import json
import threading
import urllib.request
from http.server import HTTPServer
from pathlib import Path

import pytest

from core.edge.embedding.service import EmbeddingHandler, LocalEmbedder

CORE_ROOT = Path(__file__).resolve().parents[3]
MODEL_DIR = CORE_ROOT / "models" / "embedding"

# 同义改写：应被判为高度相似。
PARAPHRASE = ("我妈妈叫李芳", "我的母亲名字是李芳")
# 无关内容：应被判为低相似。
UNRELATED = "今天天气很好"

# 同义句余弦相似度下限。
MIN_PARAPHRASE_SIMILARITY = 0.70
# 无关句余弦相似度上限 —— 它同时充当"判别力"的门槛。
MAX_UNRELATED_SIMILARITY = 0.60


@pytest.fixture()
def embedder() -> LocalEmbedder:
    """构造加载真实模型的嵌入器；模型缺失时跳过测试。

    :return: 已加载模型的嵌入器
    """
    if not (MODEL_DIR / "model.onnx").exists():
        pytest.skip(f"嵌入模型未就绪（{MODEL_DIR}），请先执行 core/scripts/fetch-models.ps1")
    return LocalEmbedder(MODEL_DIR)


def cosine(left: list[float], right: list[float]) -> float:
    """计算两个向量的余弦相似度。

    :param left:  左侧向量
    :param right: 右侧向量
    :return: 余弦相似度
    """
    return sum(a * b for a, b in zip(left, right))


def test_同义句相似度高于门槛(embedder):
    """同义改写应达到相似度门槛，否则说明模型或归一化有问题。"""
    vectors = embedder.embed_batch(list(PARAPHRASE))
    similarity = cosine(vectors[0], vectors[1])
    assert similarity >= MIN_PARAPHRASE_SIMILARITY, (
        f"同义句余弦 {similarity:.4f} 低于门槛 {MIN_PARAPHRASE_SIMILARITY}"
    )


def test_无关句相似度低于门槛(embedder):
    """无关内容的相似度应显著低于同义句，否则模型没有判别力。"""
    vectors = embedder.embed_batch([PARAPHRASE[0], UNRELATED])
    similarity = cosine(vectors[0], vectors[1])
    assert similarity <= MAX_UNRELATED_SIMILARITY, (
        f"无关句余弦 {similarity:.4f} 高于门槛 {MAX_UNRELATED_SIMILARITY}"
    )


def test_向量维度为五百一十二且已归一化(embedder):
    """向量维度应为 512 且模长为 1（归一化保证余弦可比）。"""
    vectors = embedder.embed_batch(["维度检查"])
    vector = vectors[0]
    assert len(vector) == 512
    norm = sum(value * value for value in vector) ** 0.5
    assert abs(norm - 1.0) < 1e-6


def test_服务端点返回可用向量():
    """HTTP 端点应返回可用的向量，而不只是状态 200。"""
    if not (MODEL_DIR / "model.onnx").exists():
        pytest.skip("嵌入模型未就绪")

    EmbeddingHandler.embedder = LocalEmbedder(MODEL_DIR)
    http_server = HTTPServer(("127.0.0.1", 0), EmbeddingHandler)
    thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    thread.start()
    host, port = http_server.server_address[0], http_server.server_address[1]
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/embeddings",
            data=json.dumps({"input": list(PARAPHRASE)}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    finally:
        http_server.shutdown()
        http_server.server_close()

    assert payload["dimensions"] == 512
    assert len(payload["data"]) == 2
    similarity = cosine(payload["data"][0]["embedding"], payload["data"][1]["embedding"])
    assert similarity >= MIN_PARAPHRASE_SIMILARITY
