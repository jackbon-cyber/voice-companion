"""device-ref 参考实现的交付文档测试。

参考实现最大的风险是**被当成已完成的产品**：
README 里如果没说清哪些部分没在真机验证过，
接手的人会把骨架当可用实现来做排期。

因此本测试盯住两件事：
1. README 必须显式列出未验证项，且不能是空话；
2. README 声明的每个目录/产物必须真实存在 —— 指向不存在路径的文档等于没有文档。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# 仓库根。测试位于 core/tests/device_ref/，仓库根在其上三层。
REPO_ROOT = Path(__file__).resolve().parents[3]

# device-ref 根目录。
DEVICE_REF_DIR = REPO_ROOT / "device-ref"

# README 路径。
README_PATH = DEVICE_REF_DIR / "README.md"


def _readme() -> str:
    """读取 device-ref README。

    @return README 文本
    """
    return README_PATH.read_text(encoding="utf-8")


def test_readme_exists():
    """README 必须存在。"""
    assert README_PATH.is_file(), f"缺少 device-ref README：{README_PATH}"


def test_readme_lists_unverified_section():
    """README 必须有明确的"未验证项"小节。"""
    text = _readme()
    assert re.search(r"^##\s*未验证项", text, re.MULTILINE), "README 缺少「未验证项」小节"


def test_readme_unverified_items_are_concrete():
    """未验证项必须是具体的条目，不能是空话。

    为什么："功能未经验证"这种总括性说法无法指导排期；
    必须写清**哪一部分**没验证、**怎么才算验证过**。
    """
    text = _readme()
    section = text.split("## 未验证项", 1)[1]
    # 到下一个二级标题为止。
    section = re.split(r"^##\s", section, maxsplit=1, flags=re.MULTILINE)[0]

    # 逐条抓取未验证项：按行扫描，条目与其后的缩进续行归为一块。
    blocks: list[tuple[str, str]] = []
    current_title = ""
    current_body: list[str] = []
    for line in section.splitlines():
        match = re.match(r"^- \[ \]\s+\*\*(.+?)\*\*\s*(.*)$", line)
        if match:
            if current_title:
                blocks.append((current_title, "\n".join(current_body)))
            current_title = match.group(1)
            current_body = [match.group(2)]
        elif current_title and line.startswith("  "):
            current_body.append(line.strip())
        elif current_title and not line.strip():
            continue
        elif current_title:
            blocks.append((current_title, "\n".join(current_body)))
            current_title = ""
            current_body = []
    if current_title:
        blocks.append((current_title, "\n".join(current_body)))

    assert len(blocks) >= 5, f"未验证项条目过少：{len(blocks)}"

    # 每条都要说明"未验证什么"与"怎么才算验证过"，而不是只写个标题。
    for title, body in blocks:
        assert len(title.strip()) >= 2, f"未验证项标题过短：{title}"
        assert "验证方式" in body, (
            f"未验证项未说明验证方式：{title}"
        )


@pytest.mark.parametrize(
    "relative_path",
    [
        "firmware/include/vc_protocol.h",
        "firmware/include/vc_audio_task.h",
        "firmware/include/vc_asr_task.h",
        "firmware/include/vc_intent_task.h",
        "firmware/include/vc_state_machine.h",
        "model-package/manifest.schema.json",
        "model-package/package_model.py",
        "ota/ota_update.py",
    ],
)
def test_readme_referenced_paths_exist(relative_path: str):
    """README 指向的每个产物都必须真实存在。"""
    assert (DEVICE_REF_DIR / relative_path).is_file(), (
        f"README 指向不存在的路径：{relative_path}"
    )


def test_readme_declares_firmware_task_division():
    """README 必须说明固件的任务划分。

    为什么：任务划分是固件骨架的核心产出 ——
    没有划分，四个头文件只是四个孤立文件，看不出谁跟谁协作。
    """
    text = _readme()
    assert "任务划分" in text, "README 未说明固件任务划分"
    for task in ("VAD", "ASR", "意图", "状态机"):
        assert task in text, f"README 的任务划分缺少：{task}"


def test_readme_states_protocol_is_shared_with_simulator():
    """README 必须说明设备侧与模拟端共用同一份协议。

    为什么：这是本仓库"换设备不改协议"这一设计前提的落点；
    读的人不知道这一点，就会把协议复制进设备目录，造成两份契约。
    """
    text = _readme()
    assert "core/protocol/schema" in text, "README 未指向共享协议目录"
