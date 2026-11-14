"""端云协议 JSON Schema 的加载与缓存。

Schema 是端云两侧的唯一契约来源：Python 侧与 Java 侧读同一批文件，
由各自的契约校验测试保证对同一组样例消息的判定结论一致。
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parent / "schema"

SCHEMA_NAMES: tuple[str, ...] = (
    "audio-frame",
    "voice-chunk",
    "text-reply",
    "session",
    "audio-negotiation",
    "degrade-level",
    "control-channel",
    "intent-report",
)

# 协议 schema 的 URI 前缀，与各 schema 文件里的 $id 一致。
SCHEMA_URI_PREFIX = "https://voice-companion/protocol/"


@lru_cache(maxsize=len(SCHEMA_NAMES))
def load_schema(name: str) -> dict:
    """按名称加载一份 JSON Schema，结果被缓存。

    @param name schema 名（不含 ``.schema.json`` 后缀）
    @return 解析后的 schema 字典
    @throws KeyError 名称不在已知清单内时抛出
    """
    if name not in SCHEMA_NAMES:
        raise KeyError(f"unknown protocol schema: {name}")
    schema_path = SCHEMA_DIR / f"{name}.schema.json"
    return json.loads(schema_path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def build_registry() -> "Registry":
    """构建本地 schema 注册表。

    协议 schema 之间存在相对引用（例如 ``session.schema.json`` 引用
    ``audio-negotiation.schema.json``）。不注册本地资源时，这些引用会被
    当成远程 URL 去下载 —— 既慢，又会让校验在离线环境下直接失败。

    @return 全部协议 schema 的注册表
    """
    from referencing import Registry, Resource

    resources = []
    for name in SCHEMA_NAMES:
        schema = load_schema(name)
        resources.append(
            (f"{SCHEMA_URI_PREFIX}{name}.schema.json", Resource.from_contents(schema))
        )
    return Registry().with_resources(resources)
