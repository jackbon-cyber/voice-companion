"""接口契约文档与 schema 的一致性检查。

文档会漂移：schema 改了、文档没改，接手的人按文档实现就会出错。
这里用测试把文档钉在 schema 上。
"""

from __future__ import annotations

import re
from pathlib import Path

from core.protocol.loader import SCHEMA_NAMES

# 契约文档路径。测试位于 core/tests/protocol/，仓库根在其上三层。
CONTRACT_DOC = Path(__file__).resolve().parents[3] / "docs" / "interface-contract" / "README.md"


def _doc_text() -> str:
    """读取契约文档全文。

    @return 文档文本
    """
    return CONTRACT_DOC.read_text(encoding="utf-8")


def test_contract_doc_exists():
    assert CONTRACT_DOC.exists(), f"接口契约文档缺失：{CONTRACT_DOC}"


def test_every_schema_is_documented():
    """每份 schema 都要在契约文档里出现 —— 漏写等于没有契约。"""
    text = _doc_text()

    missing = [name for name in SCHEMA_NAMES if name not in text]

    assert not missing, f"契约文档缺少这些消息的说明：{missing}"


def test_every_documented_message_type_maps_to_a_schema():
    """文档里出现的消息类型必须都能找到对应 schema。"""
    text = _doc_text()

    # 文档表格第一列用的是 schema 文件名（不含 .schema.json 后缀）。
    referenced = set(re.findall(r"`([a-z][a-z0-9-]+)\.schema\.json`", text))

    unknown = referenced - set(SCHEMA_NAMES)

    assert not unknown, f"契约文档引用了不存在的 schema：{sorted(unknown)}"


def test_doc_covers_required_fields_of_audio_frame():
    """音频帧的关键字段必须在文档里说明 —— 这是最容易漏的必填项。"""
    text = _doc_text()

    for field in ("sessionId", "sequence", "timestampMs", "sampleRate", "payloadBase64"):
        assert f"`{field}`" in text, f"音频帧字段 {field} 未在契约文档中说明"


def test_doc_explains_compatibility_rules():
    text = _doc_text()

    assert "兼容性" in text
    assert "不兼容" in text


def test_doc_points_to_validation_script():
    """文档必须指向校验入口，否则验证规则形同虚设。"""
    text = _doc_text()

    assert "validate-protocol.ps1" in text
