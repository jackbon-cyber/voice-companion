"""把合并产物相对 parts/ 源文件的增量回填到对应 part。

背景
----
docs/architecture/语音情感陪伴机器人_技术架构方案_V1.0.md 是由
tools/build_companion_doc.py 从 docs/architecture/parts/*.md 拼接生成的。
但实测内容（§1.1.1、§7.6.1、§7.6.2 等）一度只改在合并产物上，
源文件 parts/ 并未同步 —— 下次跑构建脚本，这些内容会被静默覆盖。

本脚本做的是**回填**：比对"parts 拼接结果"与"当前产物"，把只存在于产物里的
插入块，按位置写回对应的 part 源文件。回填后 parts 与产物一致，
构建脚本可以安全重跑。

用法（在仓库根目录执行）：
    F:\\tools\\python313\\python.exe tools\\sync_parts_from_product.py [--check]

--check 只报告差异不写文件，用于校验是否还有未回填的漂移。
"""

from __future__ import annotations

import argparse
import difflib
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
PARTS_DIR = os.path.join(ROOT, "docs", "architecture", "parts")
PRODUCT_PATH = os.path.join(
    ROOT, "docs", "architecture", "语音情感陪伴机器人_技术架构方案_V1.0.md"
)

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

# part 文件内部的 strip() 与拼接时的 "\n\n<!-- PAGEBREAK -->\n\n" 造成的偏移。
PART_JOIN_OFFSET = 4  # 每个 PAGEBREAK 块占 4 行（空行 + 标记 + 空行 + 空行）


def read_part(name: str) -> list[str]:
    """读取 part 源文件的行列表。

    @param name part 文件名
    @return 行列表
    """
    with open(os.path.join(PARTS_DIR, name), encoding="utf-8") as handle:
        return handle.read().strip().splitlines()


def build_joined_lines() -> tuple[list[str], list[tuple[int, int]]]:
    """构造 parts 拼接后的行列表及各 part 的行区间。

    @return (拼接行列表, [(part起始行, part结束行), ...])
    """
    joined: list[str] = []
    ranges: list[tuple[int, int]] = []
    for index, name in enumerate(PART_ORDER):
        if index:
            # 分隔符 "\n\n<!-- PAGEBREAK -->\n\n" 在行层面展开后是 3 行：
            # 一个空行、标记行、一个空行。
            joined.append("")
            joined.append("<!-- PAGEBREAK -->")
            joined.append("")
        lines = read_part(name)
        start = len(joined)
        joined.extend(lines)
        ranges.append((start, len(joined)))
    return joined, ranges


def locate_part(offset: int, ranges: list[tuple[int, int]]) -> tuple[int, int]:
    """把拼接行号定位到所属 part 与 part 内相对行号。

    行号可能落在两个 part 之间的 PAGEBREAK 间隙里 ——
    那不属于任何 part 的正文，应归属到**下一个** part 的开头（相对行号 0）。
    这样"在两个 part 之间插入内容"的语义是：内容进入下一个 part 的顶部。

    @param offset 拼接后的全局行号
    @param ranges 各 part 的行区间
    @return (part 序号, part 内相对行号)
    """
    for index, (start, end) in enumerate(ranges):
        if start <= offset <= end:
            return index, offset - start
    # 落在最后一个 part 之后：归属到最后一个 part 的末尾。
    if not ranges:
        raise ValueError("没有任何 part 区间")
    last_index = len(ranges) - 1
    last_start, last_end = ranges[last_index]
    if offset > last_end:
        return last_index, last_end - last_start
    # 落在间隙里：归属到下一个 part 的开头。
    for index, (start, _end) in enumerate(ranges):
        if offset < start:
            return index, 0
    raise ValueError(f"行号 {offset} 不在任何 part 区间内")


def collect_inserts() -> list[tuple[int, int, list[str]]]:
    """找出只存在于产物、不存在于 parts 拼接结果的插入块。

    @return [(part 序号, part 内相对行号, 插入行), ...]
    """
    joined, ranges = build_joined_lines()
    with open(PRODUCT_PATH, encoding="utf-8") as handle:
        product = handle.read().strip().splitlines()

    matcher = difflib.SequenceMatcher(None, joined, product, autojunk=False)
    inserts: list[tuple[int, int, list[str]]] = []
    for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
        if tag != "insert":
            continue
        part_index, local_offset = locate_part(_i1, ranges)
        inserts.append((part_index, local_offset, product[j1:j2]))
    return inserts


def apply_inserts(inserts: list[tuple[int, int, list[str]]]) -> list[str]:
    """把插入块写回各 part 源文件。

    @param inserts 插入块列表
    @return 被改动的 part 文件名列表
    """
    by_part: dict[int, list[tuple[int, list[str]]]] = {}
    for part_index, local_offset, lines in inserts:
        by_part.setdefault(part_index, []).append((local_offset, lines))

    changed: list[str] = []
    for part_index, entries in by_part.items():
        name = PART_ORDER[part_index]
        lines = read_part(name)
        # 倒序插入，避免前面的插入把后面的行号顶掉。
        for local_offset, block in sorted(entries, key=lambda item: -item[0]):
            lines[local_offset:local_offset] = block
        path = os.path.join(PARTS_DIR, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines).strip() + "\n")
        changed.append(name)
    return changed


def main() -> int:
    """入口。

    @return 退出码：0 表示一致或已回填，1 表示仍有非插入类差异
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="只报告，不写文件")
    args = parser.parse_args()

    inserts = collect_inserts()

    joined, _ranges = build_joined_lines()
    with open(PRODUCT_PATH, encoding="utf-8") as handle:
        product = handle.read().strip().splitlines()

    matcher = difflib.SequenceMatcher(None, joined, product, autojunk=False)
    non_insert = [
        opcode for opcode in matcher.get_opcodes() if opcode[0] in ("delete", "replace")
    ]

    if not inserts and not non_insert:
        print("parts 源文件与合并产物一致，无需回填。")
        return 0

    if non_insert:
        print(f"存在 {len(non_insert)} 处删除/替换类差异，需要人工确认：")
        for tag, i1, i2, j1, j2 in non_insert:
            print(f"  {tag} parts[{i1}:{i2}] -> prod[{j1}:{j2}]")

    print(f"发现 {len(inserts)} 处插入块，需回填到 {len(set(i for i, _, _ in inserts))} 个 part 源文件：")
    for part_index, local_offset, block in inserts:
        preview = block[0][:80] if block else ""
        print(f"  {PART_ORDER[part_index]} 第 {local_offset} 行后插入 {len(block)} 行：{preview}")

    if args.check:
        return 0

    changed = apply_inserts(inserts)
    print(f"已回填：{', '.join(changed)}")

    # 回填后必须能重建出与产物一致的内容，否则说明落点算错了。
    joined_after, _ = build_joined_lines()
    if joined_after != product:
        print("回填后重建结果与产物仍不一致，请检查落点。")
        return 1
    print("回填后重建结果与产物一致。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
