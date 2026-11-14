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
)


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
