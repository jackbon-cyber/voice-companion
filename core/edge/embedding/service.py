"""本地嵌入服务 —— 基于 ONNX Runtime 的中文语义嵌入。

存在的理由
----------
本作品的评测门禁要求"记忆召回"维度给出**真实语义**的召回率，
而不是桩嵌入测出来的词面重叠率。远端嵌入 API 需要 API 凭据，
而"克隆下来就能跑"是本作品面向求职场景的第一目标，
因此把嵌入能力做成**随仓库走的本地服务**。

技术选型
--------
* 推理后端：``onnxruntime``（CPU），无需 GPU 与 CUDA
* 模型：BGE-small-zh-v1.5 的量化 ONNX（22.9 MB，512 维）
* 分词：``tokenizers`` 直接读 ``tokenizer.json``，不引入 ``transformers``
  —— 后者会拖入 PyTorch（数百 MB），与"零重型依赖"的目标冲突

实测口径（见 ``docs/adr/ADR-011-local-embedding-service.md``）
-----------------------------------------------------------
* 稳态单条嵌入：约 2.2 ms
* 同义句余弦相似度：0.88
* 无关句余弦相似度：0.28
* 池化方式：**均值池化**。实测在记忆召回场景下优于 CLS 池化
  （Top-1 正确率 84.6% → 92.3%），意图分类场景两者打平（均 100%）。

接口
----
提供 OpenAI 兼容的 ``POST /v1/embeddings`` 与 ``GET /v1/health``，
这样 Java 侧的 ``EmbeddingService`` 实现与远端路径共用同一套请求格式，
切换嵌入来源不需要改调用方。
"""

from __future__ import annotations

import argparse
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

LOGGER = logging.getLogger("voice.embedding")

# 嵌入向量维度，必须与模型实际输出维度一致，否则下游 Chroma 集合维度校验会失败。
EMBEDDING_DIMENSIONS = 512

# 模型文件在仓库内的相对位置。
DEFAULT_MODEL_DIR = Path("core/models/embedding")

# 请求体里可能出现的文本字段，按顺序尝试取值。
TEXT_FIELDS = ("input", "text", "content")

# 单次请求允许的最大条数，防止一个超大请求把内存打满。
MAX_BATCH_SIZE = 64

# 池化方式：取全部 token 向量的均值。
#
# **为什么改用均值池化**（这是一个由实测推翻先前结论的修订）：
# 原实现用 CLS 位置，注释称"实测 CLS 在中文短句上的判别力优于均值池化"。
# 那条结论来自**意图原型分类**场景，不能直接套到**记忆召回**场景 ——
# 嵌入服务是同一个进程、同一个模型，池化方式是全局选择。
#
# 在同一批 13 条记忆召回评测集上实测（问句 ↔ 13 条记忆原文）：
#
#   池化    记忆召回 Top-1 正确率    意图分类准确率
#   CLS     11/13 = 84.6%            15/15 = 100%
#   均值    12/13 = 92.3%            15/15 = 100%
#
# 意图分类上两者打平，记忆召回上均值更好，且不相关对的距离下限更高
# （CLS 1.0434 → 均值 1.1750），区分度更好。
# 因此改用均值池化。**任何时候改动池化都必须同时复测这两个场景** ——
# 只看其中一个场景就改全局配置，是"优化了一个数、坏了另一个数"的典型成因。
POOLING_MEAN = "mean"


class LocalEmbedder:
    """本地 ONNX 嵌入推理器。

    模型与会话在**首次使用时**加载，之后复用同一会话 ——
    onnxruntime 的会话创建代价（实测约 2.3 秒）远高于单次推理（2.2 毫秒），
    每请求重建会话会让嵌入成为整个链路的性能瓶颈。
    """

    def __init__(self, model_dir: Path) -> None:
        self._model_dir = model_dir
        self._session: Any = None
        self._tokenizer: Any = None
        self._lock = threading.Lock()

    def _ensure_loaded(self) -> None:
        """确保模型与分词器已加载。

        用锁保护：多线程同时首次访问时，只允许一个线程真正加载，
        其余线程等待后直接使用已加载的实例。
        """
        if self._session is not None:
            return
        with self._lock:
            if self._session is not None:
                return
            self._load()

    def _load(self) -> None:
        """从磁盘加载 ONNX 模型与分词器。

        :raises FileNotFoundError 模型文件缺失时抛出，消息指明缺失路径与获取方式
        """
        import onnxruntime as ort
        from tokenizers import Tokenizer

        model_path = self._model_dir / "model.onnx"
        tokenizer_path = self._model_dir / "tokenizer.json"

        missing = [path for path in (model_path, tokenizer_path) if not path.exists()]
        if missing:
            names = "、".join(str(path) for path in missing)
            raise FileNotFoundError(
                f"嵌入模型缺失：{names}。"
                "请先执行 core/scripts/fetch-models.ps1 下载模型权重。"
            )

        LOGGER.info("加载嵌入模型：%s", model_path)
        self._session = ort.InferenceSession(
            str(model_path), providers=["CPUExecutionProvider"]
        )
        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        LOGGER.info("嵌入模型就绪，维度 %d", EMBEDDING_DIMENSIONS)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量计算嵌入向量。

        :param texts: 待嵌入的文本列表
        :return: 与入参等长的向量列表
        """
        if not texts:
            return []
        self._ensure_loaded()
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        """计算单条文本的嵌入向量。

        :param text: 待嵌入文本
        :return: 单位长度的向量
        """
        import numpy as np

        encoding = self._tokenizer.encode(text)
        input_ids = np.array([encoding.ids], dtype=np.int64)
        attention_mask = np.ones_like(input_ids)
        outputs = self._session.run(
            None,
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "token_type_ids": np.zeros_like(input_ids),
            },
        )
        hidden = outputs[0][0]
        if POOLING_MEAN == "mean":
            vector = hidden.mean(axis=0)
        else:
            vector = hidden[0]
        return normalize(vector).tolist()


def normalize(vector: Any) -> Any:
    """把向量归一化到单位长度。

    归一化的必要性：下游按余弦相似度排序，未归一化的向量会让模长影响排序，
    表现为"长文本永远更相似"这类难以定位的问题。

    :param vector: 待归一化的向量，可以是 numpy 数组或普通序列
    :return: 单位长度的向量；零向量原样返回
    """
    import numpy as np

    array = np.asarray(vector, dtype=np.float64)
    norm = float(np.linalg.norm(array))
    if norm <= 0.0:
        return array
    return array / norm


def collect_texts(payload: dict[str, Any]) -> list[str]:
    """从请求体中收集待向量化的文本。

    :param payload: 已解析的请求体
    :return: 文本列表
    """
    for field in TEXT_FIELDS:
        value = payload.get(field)
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            texts: list[str] = []
            for item in value:
                if isinstance(item, str):
                    texts.append(item)
                elif isinstance(item, dict) and "text" in item:
                    texts.append(str(item["text"]))
            if texts:
                return texts
    return []


class EmbeddingHandler(BaseHTTPRequestHandler):
    """嵌入服务的 HTTP 处理器。"""

    embedder: LocalEmbedder

    def log_message(self, format: str, *args: Any) -> None:
        """把访问日志转到标准错误，避免污染 stdout 的 JSON 输出。"""
        LOGGER.info("[embedding] " + format % args)

    def do_GET(self) -> None:
        """处理健康检查。"""
        if self.path.endswith("/health"):
            self.respond({"status": "UP", "dimensions": EMBEDDING_DIMENSIONS})
            return
        self.respond({"error": {"message": "unsupported path: " + self.path}}, status=404)

    def do_POST(self) -> None:
        """处理嵌入请求。"""
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            payload = {}

        if not self.path.endswith("/embeddings"):
            self.respond({"error": {"message": "unsupported path: " + self.path}}, status=404)
            return

        texts = collect_texts(payload)
        if not texts:
            self.respond({"error": {"message": "no input text found"}}, status=400)
            return
        if len(texts) > MAX_BATCH_SIZE:
            self.respond(
                {"error": {"message": f"batch size {len(texts)} exceeds limit {MAX_BATCH_SIZE}"}},
                status=400,
            )
            return

        try:
            vectors = self.embedder.embed_batch(texts)
        except FileNotFoundError as error:
            self.respond({"error": {"message": str(error)}}, status=503)
            return
        except Exception as error:  # noqa: BLE001 - 推理失败必须转成 HTTP 状态，不能让线程崩溃
            LOGGER.exception("嵌入计算失败")
            self.respond({"error": {"message": str(error)}}, status=500)
            return

        self.respond(
            {
                "object": "list",
                "data": [
                    {"object": "embedding", "index": index, "embedding": vector}
                    for index, vector in enumerate(vectors)
                ],
                "model": payload.get("model", "local-bge-small-zh"),
                "dimensions": EMBEDDING_DIMENSIONS,
            }
        )

    def respond(self, payload: dict[str, Any], status: int = 200) -> None:
        """写出 JSON 响应。

        :param payload: 响应体
        :param status: HTTP 状态码
        """
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    """启动本地嵌入服务。"""
    parser = argparse.ArgumentParser(description="本地 ONNX 嵌入服务")
    parser.add_argument("--port", type=int, default=8766, help="监听端口，默认 8766")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument(
        "--model-dir",
        default=str(DEFAULT_MODEL_DIR),
        help="模型目录，默认 core/models/embedding",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    EmbeddingHandler.embedder = LocalEmbedder(Path(args.model_dir))
    server = HTTPServer((args.host, args.port), EmbeddingHandler)
    LOGGER.info("本地嵌入服务已启动：http://%s:%d/v1", args.host, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("本地嵌入服务已停止")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
