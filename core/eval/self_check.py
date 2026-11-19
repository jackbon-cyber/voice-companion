"""评测集自检（不连接任何依赖服务）。

自检的目标很具体：<b>在跑真实评测之前，先确认评测集本身是有效的</b>。

三类检查
--------
1. **格式检查**：每行必须是 ``维度|输入|期望``（或四段的
   ``维度|输入|期望|记忆原文``），维度必须已知。
2. **样本规模检查**：每个云端维度至少要有一定数量的样本 ——
   样本太少时统计量不具统计意义，跑出来的门禁判定是自欺欺人。
3. **语料交集检查**：意图与记忆召回两个维度的评测样本
   不能与生产语料（原型示例句、记忆关键词）字面重合。

为什么不做全维度的交集检查
--------------------------
安全与共情两个维度靠<b>词表规则</b>产出结果，评测样本本来就必须触发这些规则
—— 造出一堆规则覆盖不到的句子，测出来的召回率与真实能力无关。
这类维度的字面重叠属于设计使然，改为在报告中如实披露。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 评测集目录相对仓库根。
DEFAULT_EVAL_DIR = "core/eval"

# 评测集文件后缀。
FILE_SUFFIX = "-eval.txt"

# 云端维度。由 Java 侧的 EvalDimension 镜像而来，两边必须一致。
CLOUD_DIMENSIONS: tuple[str, ...] = (
    "intent",
    "memory_recall",
    "memory_answer",
    "safety",
    "empathy",
)

# 端侧维度。由 Python 侧的评测器执行。
EDGE_DIMENSIONS: tuple[str, ...] = (
    "asr",
)

# 要求与生产语料严格不相交的维度。
# 这些维度靠学习产出结果，评测句与训练句重复就是在测背诵而非泛化。
STRICT_DISJOINT_DIMENSIONS: tuple[str, ...] = (
    "intent",
    "memory_recall",
    "memory_answer",
)

# 参与门禁判定所需的最小样本数。与 EvalGates.MIN_SAMPLE_SIZE 保持一致。
MIN_SAMPLE_SIZE = 10

# 退出码：全部通过。
EXIT_PASSED = 0

# 退出码：自检失败。
EXIT_SELF_CHECK_FAILED = 3


def _read_lines(path: Path) -> list[tuple[int, str]]:
    """读取文件中的有效行。

    :param path: 文件路径
    :return: (行号, 行内容) 列表；空行与注释行被排除
    """
    entries: list[tuple[int, str]] = []
    with path.open("r", encoding="utf-8") as handle:
        for number, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            entries.append((number, line))
    return entries


def _dimension_of(path: Path) -> str:
    """从文件名推断评测维度。

    :param path: 文件路径
    :return: 维度名（小写，如 ``intent``）
    """
    stem = path.stem
    if stem.endswith(FILE_SUFFIX.removesuffix(".txt")):
        stem = stem[: -len(FILE_SUFFIX.removesuffix(".txt"))]
    return stem.lower()


def _parse(path: Path, entries: list[tuple[int, str]]) -> list[tuple[str, str, str]]:
    """解析评测集文件。

    :param path: 文件路径，用于错误提示
    :param entries: 有效行
    :return: (维度, 输入, 期望) 三元组列表
    :raises ValueError: 格式错误时抛出
    """
    dimension = _dimension_of(path)
    samples: list[tuple[str, str, str]] = []
    for number, line in entries:
        parts = line.split("|")
        if len(parts) not in (3, 4, 5):
            raise ValueError(
                f"{path} 第 {number} 行：期望 3 段（维度|输入|期望）、"
                f"4 段（维度|输入|期望|记忆原文）或 5 段（维度|输入|期望|记忆原文|期望内容），"
                f"实际 {len(parts)} 段"
            )
        if parts[0].lower() != dimension:
            raise ValueError(
                f"{path} 第 {number} 行：维度标注为 '{parts[0]}'，"
                f"但文件名表明它是 '{dimension}'"
            )
        samples.append((parts[0].lower(), parts[1], parts[2]))
    return samples


def _normalize(text: str) -> str:
    """归一化文本用于交集判定。

    :param text: 原始文本
    :return: 去掉标点与空白后的小写文本
    """
    for char in " \t，。！？、,.!?：:；;\"'“”‘’（）()【】":
        text = text.replace(char, "")
    return text.lower()


def _load_corpus() -> set[str]:
    """读取生产语料（意图原型示例句与端侧规则关键词）。

    :return: 归一化后的语料集合
    """
    corpus: set[str] = set()
    try:
        from core.edge.intent.rules import DEFAULT_RULES
    except ImportError:
        return corpus

    for rule in DEFAULT_RULES:
        for keyword in rule.keywords:
            corpus.add(_normalize(keyword))
    return corpus


def self_check(eval_dir: Path) -> int:
    """执行自检。

    :param eval_dir: 评测集目录
    :return: 进程退出码
    """
    if not eval_dir.is_dir():
        print(f"自检失败：评测集目录不存在：{eval_dir}", file=sys.stderr)
        return EXIT_SELF_CHECK_FAILED

    problems: list[str] = []
    sample_counts: dict[str, int] = {}

    for path in sorted(eval_dir.glob(f"*{FILE_SUFFIX}")):
        dimension = _dimension_of(path)
        try:
            samples = _parse(path, _read_lines(path))
        except ValueError as error:
            problems.append(str(error))
            continue
        sample_counts[dimension] = len(samples)

        known = CLOUD_DIMENSIONS + EDGE_DIMENSIONS
        if dimension not in known:
            problems.append(f"{path.name}：未知维度 '{dimension}'")
            continue

        if dimension in STRICT_DISJOINT_DIMENSIONS:
            corpus = _load_corpus()
            for _, text, _ in samples:
                if _normalize(text) in corpus:
                    problems.append(
                        f"{path.name}：评测样本 '{text}' 与生产语料字面重合"
                        f"（{dimension} 维度要求严格不相交）"
                    )

    for dimension in CLOUD_DIMENSIONS:
        count = sample_counts.get(dimension, 0)
        if count == 0:
            problems.append(f"{dimension} 维度没有评测样本")
        elif count < MIN_SAMPLE_SIZE:
            problems.append(
                f"{dimension} 维度只有 {count} 条样本，少于最小样本数 {MIN_SAMPLE_SIZE}"
            )

    if problems:
        print("自检失败：", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return EXIT_SELF_CHECK_FAILED

    for dimension, count in sorted(sample_counts.items()):
        print(f"自检通过：{dimension} 维度 {count} 条样本")
    print("自检通过：评测集与生产语料交集为空")
    return EXIT_PASSED


def main() -> None:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="评测集自检")
    parser.add_argument("--eval-dir", default=DEFAULT_EVAL_DIR, help="评测集目录")
    args = parser.parse_args()

    raise SystemExit(self_check(Path(args.eval_dir)))


if __name__ == "__main__":
    main()
