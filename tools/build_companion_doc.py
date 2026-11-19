"""合并语音陪伴机器人方案各部分为单一 Markdown，并生成 Word。

用法（在仓库根目录执行）：
    python tools/build_companion_doc.py
产出：
    docs/architecture/语音情感陪伴机器人_技术架构方案_V1.0.md
    docs/architecture/语音情感陪伴机器人_技术架构方案_V1.0.docx

**重要**：合并产物 md 是**生成文件**。要改内容，请改 docs/architecture/parts/part*.md 源文件，
然后重跑本脚本。直接改产物会在下次构建时被静默覆盖。

改动产物后，用 tools/sync_parts_from_product.py --check 校验是否漏改了源文件；
或用该脚本（不带 --check）把产物里的增量回填回源文件。
"""
from __future__ import annotations

import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
OUT_DIR = os.path.join(ROOT, "docs", "architecture")
PARTS_DIR = os.path.join(OUT_DIR, "parts")
MD_PATH = os.path.join(OUT_DIR, "语音情感陪伴机器人_技术架构方案_V1.0.md")
DOCX_PATH = os.path.join(OUT_DIR, "语音情感陪伴机器人_技术架构方案_V1.0.docx")

PART_ORDER = [
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
]


def merge() -> str:
    """按 PART_ORDER 拼接各部分，正文与附录之间插入分页标记。"""
    blocks: list[str] = []
    for name in PART_ORDER:
        path = os.path.join(PARTS_DIR, name)
        with open(path, encoding="utf-8") as f:
            blocks.append(f.read().strip())
    body = "\n\n<!-- PAGEBREAK -->\n\n".join(blocks)
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(MD_PATH, "w", encoding="utf-8") as f:
        f.write(body + "\n")
    return MD_PATH


def check_consistent() -> bool:
    """校验合并产物与源文件是否一致。

    **为什么要有这道检查**：合并产物是生成文件。直接改产物而不改源文件，
    下次构建就会被静默覆盖 —— 改动"看起来生效了"，实则会丢失。
    这道检查让这类漂移在构建当场就暴露。

    @return 一致返回 True
    """
    blocks: list[str] = []
    for name in PART_ORDER:
        path = os.path.join(PARTS_DIR, name)
        with open(path, encoding="utf-8") as f:
            blocks.append(f.read().strip())
    expected = "\n\n<!-- PAGEBREAK -->\n\n".join(blocks) + "\n"

    if not os.path.exists(MD_PATH):
        print("合并产物不存在，将重新生成。")
        return True

    with open(MD_PATH, encoding="utf-8") as f:
        actual = f.read()

    if actual == expected:
        return True

    print("=" * 64)
    print("警告：合并产物与 parts/ 源文件不一致。")
    print("产物：docs/architecture/语音情感陪伴机器人_技术架构方案_V1.0.md")
    print("说明：产物是生成文件，直接改它会在下次构建时被覆盖。")
    print("      请改 parts/part*.md 后重跑本脚本；")
    print("      或用 tools/sync_parts_from_product.py 把产物增量回填回源文件。")
    print("=" * 64)
    return False


def to_docx() -> None:
    """调用项目既有的 md→docx 脚本（含图片插入与页脚页码）。"""
    script = os.path.join(ROOT, "tools", "md2docx_with_images.py")
    subprocess.run([sys.executable, script, MD_PATH, DOCX_PATH], check=True, cwd=ROOT)


if __name__ == "__main__":
    consistent = check_consistent()
    merge()
    to_docx()
    print(MD_PATH)
    print(DOCX_PATH)
    if not consistent:
        print("（本次构建已用 parts/ 源文件重新生成产物，产物中此前的手工改动已丢失）")
        sys.exit(1)
