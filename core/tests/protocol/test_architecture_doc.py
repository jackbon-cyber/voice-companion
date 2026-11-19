"""架构方案文档的构建一致性与引用完整性检查。

**为什么需要这套检查**

方案文档的 markdown 是**生成文件**（由 `tools/build_companion_doc.py`
从 `docs/architecture/parts/*.md` 拼接）。曾经发生过：
实测内容只改在生成产物上、源文件未同步 —— 下次跑构建脚本，
那 6300 多字符的内容**静默消失**，改完看着生效了实则丢失。

这里把两类问题钉死：
1. 产物与源文件不一致（有人直接改了生成物）；
2. 文档引用的文件/路径不存在（移动目录后留下的断链）。
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ARCH_DIR = REPO_ROOT / "docs" / "architecture"
PARTS_DIR = ARCH_DIR / "parts"
PRODUCT_PATH = ARCH_DIR / "语音情感陪伴机器人_技术架构方案_V1.0.md"

# part 文件必须覆盖的全部章节（顺序即拼接顺序）。
EXPECTED_PARTS = (
    "part00_cover.md",
    "part01_overview.md",
    "part02_edge_hardware.md",
    "part03_edge_ai.md",
    "part04_model_deploy.md",
    "part05_cloud.md",
    "part06_tts.md",
    "part07_memory.md",
    "part08_persona.md",
    "part09_performance.md",
    "part10_security.md",
    "part11_roadmap.md",
    "part12_challenges.md",
    "part13_appendix.md",
)


def _part_text(name: str) -> str:
    """读取 part 源文件文本。

    @param name part 文件名
    @return 文本内容
    """
    return (PARTS_DIR / name).read_text(encoding="utf-8")


def _joined_parts() -> str:
    """按构建脚本的规则拼接全部 part。

    @return 拼接后的文本
    """
    blocks = [_part_text(name).strip() for name in EXPECTED_PARTS]
    return "\n\n<!-- PAGEBREAK -->\n\n".join(blocks)


def test_all_parts_exist():
    """全部 part 源文件必须存在 —— 少一个就会丢一整章。"""
    missing = [name for name in EXPECTED_PARTS if not (PARTS_DIR / name).is_file()]

    assert not missing, f"缺少 part 源文件：{missing}"


def test_product_matches_parts():
    """合并产物必须与 parts/ 源文件一致。

    **这是本文件最关键的一条**：不一致意味着有人直接改了生成产物，
    那份改动会在下次构建时被静默覆盖。
    """
    expected = _joined_parts() + "\n"
    actual = PRODUCT_PATH.read_text(encoding="utf-8")

    assert actual == expected, (
        "合并产物与 parts/ 源文件不一致 —— 请改 docs/architecture/parts/*.md "
        "后重跑 tools/build_companion_doc.py；"
        "若要把产物里的改动保留下来，先用 tools/sync_parts_from_product.py 回填。"
    )


def test_build_script_detects_drift():
    """构建脚本必须能发现产物漂移并以非零码退出。

    **为什么不能只看代码**：一致性检查逻辑本身也可能被改坏。
    这里真的动一下产物，跑构建脚本，验证它会拦下来。

    **注意**：本测试会重建产物，因此必须在
    `test_product_matches_parts` 之前或之后执行都不能影响它 ——
    结束时会把产物还原成与源文件一致的状态。
    """
    original = PRODUCT_PATH.read_text(encoding="utf-8")
    try:
        PRODUCT_PATH.write_text(original + "\n<!-- 漂移探测 -->\n", encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "build_companion_doc.py")],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )

        assert result.returncode != 0, "构建脚本未检测出产物漂移"
        assert "不一致" in result.stdout, "构建脚本未给出漂移告警"
    finally:
        # 构建脚本已用源文件重建产物；这里再跑一次确保最终一致。
        subprocess.run(
            [sys.executable, str(REPO_ROOT / "tools" / "build_companion_doc.py")],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
        )


def test_product_images_exist():
    """方案文档里引用的架构图必须真实存在。

    图片路径是相对文档目录的 —— 移动目录后最容易在这里断链。
    """
    text = PRODUCT_PATH.read_text(encoding="utf-8")
    referenced = set(re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text))

    missing = sorted(path for path in referenced if not (ARCH_DIR / path).is_file())

    assert not missing, f"方案文档引用了不存在的图片：{missing}"


def test_part_images_exist():
    """part 源文件里引用的架构图也必须存在（产物是由 part 拼出来的）。"""
    missing: list[str] = []
    for name in EXPECTED_PARTS:
        text = _part_text(name)
        for path in set(re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text)):
            if not (ARCH_DIR / path).is_file():
                missing.append(f"{name} -> {path}")

    assert not missing, f"part 源文件引用了不存在的图片：{missing}"


def test_architecture_readme_points_to_all_parts():
    """架构目录的 README 必须说明每个 part 的章节归属。

    **为什么**：接手的人若不知道 parts/ 才是源文件，
    会直接改生成产物 —— 这正是上面那条漂移的成因。
    """
    readme = (ARCH_DIR / "README.md").read_text(encoding="utf-8")

    for name in EXPECTED_PARTS:
        assert name in readme, f"架构 README 未提到 {name}"

    for keyword in ("parts/", "build_companion_doc.py", "sync_parts_from_product.py"):
        assert keyword in readme, f"架构 README 缺少关键说明：{keyword}"


def test_no_stale_voice_companion_path_references():
    """仓库内不得再有指向旧路径的引用。

    旧路径 `docs/voice-companion/` 已被 `docs/architecture/` 取代。
    残留引用会让读者找不到文件。
    """
    stale_hits: list[str] = []
    for path in REPO_ROOT.rglob("*.md"):
        relative = path.relative_to(REPO_ROOT)
        if relative.parts[0] in {".git", "target", "data"}:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if "docs/voice-companion" in text or "docs\\voice-companion" in text:
            stale_hits.append(str(relative))

    assert not stale_hits, f"仍指向旧路径 docs/voice-companion/ 的文件：{stale_hits}"
