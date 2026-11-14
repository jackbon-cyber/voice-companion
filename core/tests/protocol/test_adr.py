"""ADR 格式与完整性检查。

ADR 是给未来的人看的决策依据。格式统一、要素齐全，才能在需要时读懂。
"""

from __future__ import annotations

import re
from pathlib import Path

# 仓库根。测试位于 core/tests/protocol/，仓库根在其上三层。
REPO_ROOT = Path(__file__).resolve().parents[3]

# ADR 文档路径。
ADR_DOC = REPO_ROOT / "docs" / "adr" / "README.md"

# 每条 ADR 必须有的要素。
REQUIRED_SECTIONS: tuple[str, ...] = (
    "### 背景",
    "### 选项",
    "### 选定",
    "### 理由",
    "### 未选其他选项的原因",
    "### 代价",
)


def _adr_text() -> str:
    """读取 ADR 文档全文。

    @return 文档文本
    """
    return ADR_DOC.read_text(encoding="utf-8")


def test_adr_doc_exists():
    assert ADR_DOC.exists(), f"ADR 文档缺失：{ADR_DOC}"


def test_adr_has_at_least_ten_records():
    """十项关键权衡要有对应的决策记录。"""
    text = _adr_text()

    count = len(re.findall(r"^## ADR-\d+", text, flags=re.MULTILINE))

    assert count >= 10, f"ADR 记录数不足：{count}"


def test_every_adr_has_all_required_sections():
    """每条 ADR 的要素必须齐全 —— 缺"代价"的决策记录是不诚实的。"""
    text = _adr_text()

    records = re.split(r"^## ADR-\d+", text, flags=re.MULTILINE)[1:]

    for record in records:
        title = record.splitlines()[0].strip()
        missing = [section for section in REQUIRED_SECTIONS if section not in record]
        assert not missing, f"ADR {title} 缺少这些要素：{missing}"


def test_every_adr_has_reevaluation_condition():
    """每条 ADR 都要写清"什么情况下这个决策就不成立"。"""
    text = _adr_text()

    records = re.split(r"^## ADR-\d+", text, flags=re.MULTILINE)[1:]

    for record in records:
        title = record.splitlines()[0].strip()
        assert "什么情况下应该重新评估" in record, f"ADR {title} 缺少重新评估条件"


def test_adr_records_are_numbered_sequentially():
    """编号连续，避免出现 ADR-007 与 ADR-009 之间断档。"""
    text = _adr_text()

    numbers = [int(value) for value in re.findall(r"^## ADR-(\d+)", text, flags=re.MULTILINE)]

    assert numbers == list(range(1, len(numbers) + 1)), f"ADR 编号不连续：{numbers}"


def test_adr_mentions_real_cost_not_only_benefits():
    """每条 ADR 都要写代价 —— 只写好处的决策记录没有决策价值。"""
    text = _adr_text()

    records = re.split(r"^## ADR-\d+", text, flags=re.MULTILINE)[1:]

    for record in records:
        title = record.splitlines()[0].strip()
        cost_section = record.split("### 代价", 1)
        assert len(cost_section) == 2, f"ADR {title} 缺少代价小节"
        cost_body = cost_section[1].split("###", 1)[0].strip()
        assert len(cost_body) >= 30, f"ADR {title} 的代价小节过于简略"
