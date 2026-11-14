"""本地嵌入服务的包入口。"""

from .service import EMBEDDING_DIMENSIONS, LocalEmbedder, normalize

__all__ = ["EMBEDDING_DIMENSIONS", "LocalEmbedder", "normalize"]
