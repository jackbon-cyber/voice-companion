"""本地嵌入服务的单元测试。

测试**不加载真实模型** —— 那需要 22.9 MB 权重且依赖外部下载。
被测的逻辑（文本收集、响应格式、错误分支）用可注入的假嵌入器覆盖；
真实模型的语义质量由 ``core/scripts/verify-eval.ps1`` 的评测门禁覆盖，
两者的分工是：单测守"接口不会坏"，门禁守"能力够不够"。
"""

from __future__ import annotations

import json
import threading
from http.server import HTTPServer

import pytest

from core.edge.embedding.service import (
    EMBEDDING_DIMENSIONS,
    EmbeddingHandler,
    LocalEmbedder,
    collect_texts,
    normalize,
)


class FakeEmbedder:
    """可注入的假嵌入器：返回确定性向量，不触碰真实模型。"""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """记录调用并返回固定维度的确定性向量。

        :param texts: 待嵌入文本
        :return: 向量列表
        """
        self.calls.append(list(texts))
        return [[0.25, 0.5, 0.75] for _ in texts]


@pytest.fixture()
def server():
    """启动一个使用假嵌入器的本地服务。

    :yield: (基址, 假嵌入器) 元组
    """
    embedder = FakeEmbedder()
    EmbeddingHandler.embedder = embedder  # type: ignore[assignment]
    http_server = HTTPServer(("127.0.0.1", 0), EmbeddingHandler)
    thread = threading.Thread(target=http_server.serve_forever, daemon=True)
    thread.start()
    host, port = http_server.server_address[0], http_server.server_address[1]
    try:
        yield f"http://127.0.0.1:{port}", embedder
    finally:
        http_server.shutdown()
        http_server.server_close()


def test_健康检查返回就绪与维度(server):
    """健康检查应返回 UP 与向量维度。"""
    import urllib.request

    base_url, _ = server
    with urllib.request.urlopen(f"{base_url}/health", timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))
    assert payload["status"] == "UP"
    assert payload["dimensions"] == EMBEDDING_DIMENSIONS


def test_嵌入端点返回与输入等长的向量(server):
    """嵌入请求的向量条数应与输入条数一致。"""
    import urllib.request

    base_url, embedder = server
    request = urllib.request.Request(
        f"{base_url}/embeddings",
        data=json.dumps({"input": ["我妈妈叫李芳", "今天天气很好"]}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))

    assert payload["object"] == "list"
    assert len(payload["data"]) == 2
    assert [item["index"] for item in payload["data"]] == [0, 1]
    assert embedder.calls == [["我妈妈叫李芳", "今天天气很好"]]


def test_缺少输入文本时返回四百(server):
    """没有可嵌入的文本时应返回 400 而不是空结果。"""
    import urllib.error
    import urllib.request

    base_url, _ = server
    request = urllib.request.Request(
        f"{base_url}/embeddings",
        data=json.dumps({}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(request, timeout=5)
    assert error.value.code == 400


def test_超大批次被拒绝(server):
    """超过批量上限的请求应被拒绝，防止内存被打满。"""
    import urllib.error
    import urllib.request

    base_url, _ = server
    payload = {"input": ["文本"] * 100}
    request = urllib.request.Request(
        f"{base_url}/embeddings",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as error:
        urllib.request.urlopen(request, timeout=5)
    assert error.value.code == 400


def test_文本收集支持多种字段名():
    """文本字段的多种形态都应被识别。"""
    assert collect_texts({"input": "文本"}) == ["文本"]
    assert collect_texts({"text": "文本"}) == ["文本"]
    assert collect_texts({"content": "文本"}) == ["文本"]
    assert collect_texts({"input": ["甲", "乙"]}) == ["甲", "乙"]
    assert collect_texts({"input": [{"text": "甲"}]}) == ["甲"]
    assert collect_texts({}) == []


def test_归一化后模长为一():
    """归一化后的向量模长应为 1。"""
    import math

    vector = normalize([3.0, 4.0])
    assert math.isclose(math.sqrt(sum(value * value for value in vector)), 1.0, rel_tol=1e-9)


def test_零向量归一化后不变():
    """零向量不能被归一化成 NaN。"""
    vector = normalize([0.0, 0.0])
    assert list(vector) == [0.0, 0.0]


def test_模型文件缺失时抛出可操作的异常(tmp_path):
    """模型缺失时的异常消息必须指明获取方式，否则使用者无从下手。"""
    embedder = LocalEmbedder(tmp_path)
    with pytest.raises(FileNotFoundError) as error:
        embedder.embed_batch(["测试"])
    message = str(error.value)
    assert "fetch-models.ps1" in message
