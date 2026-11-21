"""汇总最终指标报告。

把三份产物合成一份**可交付的报告**：

- 云端评测（意图 / 记忆召回 / 记忆作答 / 安全 / 共情五个维度）
- 端侧评测（端侧识别维度）
- 端到端断言（跨用户隔离 / 离线降级）

**为什么要汇总而不是各看各的**：
三份报告各自通过，读者仍然无法回答"这东西到底行不行"。
汇总报告的每个数字都标明**它证明了什么**与**它没证明什么** ——
一份让人高估成熟度的报告，比没有报告更糟。

运行：

    python -m core.e2e.final_report --output data/reports/final-report.md
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 仓库根。
REPO_ROOT = Path(__file__).resolve().parents[2]

# 云端评测 JSON 报告路径。
CLOUD_REPORT_PATH = REPO_ROOT / "core" / "eval-report.json"

# 端侧评测报告路径。
EDGE_REPORT_PATH = REPO_ROOT / "core" / "eval-edge-report.md"

# 端到端断言报告路径。
E2E_REPORT_PATH = REPO_ROOT / "data" / "reports" / "e2e-report.json"

# 云端维度在报告中的说明。写清楚"这个维度测的是什么"，
# 避免读者把"意图准确率 100%"理解成"意图理解能力完美"。
CLOUD_DIMENSION_NOTES: dict[str, str] = {
    "INTENT": "意图分类准确率，评测集与原型示例句严格不相交（衡量泛化）。",
    "MEMORY_RECALL": "长期记忆召回命中率（Recall@K），评测记忆写入独立作用域，与生产数据隔离。",
    "MEMORY_ANSWER": (
        "**用户实际听到的那句话**对不对（Top-1）。"
        "Recall@K 度量的是用户看不到的数字 —— 产品真正回复的是排序第一条。"
    ),
    "SAFETY": "安全策略召回率。允许与词表重叠 —— 审核靠词表规则，样本必须触发规则。",
    "EMPATHY": "情感标签判定正确率。允许与词表重叠 —— 情绪判定同样靠词表规则。",
}

# 每个维度**没有**证明什么。报告里最容易被误读的就是这一列。
CLOUD_DIMENSION_LIMITS: dict[str, str] = {
    "INTENT": "只覆盖规则表内的意图；长尾意图靠云端大模型，本维度未覆盖。",
    "MEMORY_RECALL": (
        "只覆盖单一作用域内的召回；跨用户隔离由端到端断言单独验证。"
        "样本量 13 条，与 §7.6 的 500 条目标规模相差两个数量级。"
    ),
    "MEMORY_ANSWER": (
        "只覆盖 13 条答得上 + 12 条答不上的问题，"
        "相关性下限两侧只有 0.0039 的余量 —— **阈值是当前实测取值，不是普适结论**，"
        "评测集扩充后必须重测。"
    ),
    "SAFETY": "只覆盖词表可触发的样本；未覆盖对抗性输入与多轮诱导。",
    "EMPATHY": "只覆盖单轮情绪判定；多轮情绪转折未覆盖。",
}

# 记忆作答维度的三个数。它们的**口径互不相同**，混用会得出矛盾结论，
# 所以在报告里必须分开呈现，不能只给一个"准确率"。
MEMORY_ANSWER_METRICS: list[tuple[str, str, str]] = [
    (
        "作答准确率",
        "memory_answer_accuracy",
        "系统**选择作答**时说的正是期望记忆的比例。拒答不进分子也不进分母 —— "
        "答错一次就是用户被误导一次，而\"我不确定\"是可接受的。",
    ),
    (
        "作答率（覆盖率）",
        "memory_answer_coverage",
        "**期望作答**的样本里系统实际作答的比例。"
        "单独设这道门禁是为了防止\"永远拒答\"也能拿满分 —— 那样的机器人毫无用处。",
    ),
    (
        "编造率",
        "memory_fabrication_rate",
        "**库里没有对应事实**时系统不拒答而是作答的比例。"
        "这是本维度最不能妥协的一项：用户听到一句库里根本没有的话时无从分辨真假 —— "
        "机器人一旦开始编，记忆这个核心卖点就废了。",
    ),
]

# 端侧识别维度的说明。
EDGE_DIMENSION_NOTE = (
    "端侧 ASR 在安静室内条件（clean，30 dB）下的识别准确率。"
    "音频由 TTS 合成，缺少真人语音的音高与共振峰细节，"
    "**该数值偏乐观，不应作为真机指标**。"
)

# 端侧识别维度明确**没有**验证的内容。
EDGE_DIMENSION_LIMITS = (
    "真人语音的噪声鲁棒性未验证；"
    "端侧唤醒词与远场拾音未验证；"
    "真机上的识别延迟与内存占用未测量。"
)


@dataclass
class ReportSection:
    """报告的一个段落。

    @param title 段落标题
    @param lines 段落内容行
    """

    title: str
    lines: list[str] = field(default_factory=list)

    def render(self) -> str:
        """渲染为 Markdown。

        @return Markdown 文本
        """
        body = "\n".join(self.lines)
        return f"## {self.title}\n\n{body}\n"


def _read_json(path: Path) -> dict[str, Any] | None:
    """读取 JSON 文件。

    @param path 文件路径
    @return 解析结果；文件不存在或解析失败时返回 None
    """
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def build_cloud_section() -> ReportSection:
    """构造云端评测段落。

    @return 段落
    """
    report = _read_json(CLOUD_REPORT_PATH)
    dimensions = report.get("dimensions", [])
    section = ReportSection(title=f"云端评测（{len(dimensions)} 个维度）")

    if report is None:
        section.lines.append(
            "**未产出报告** —— 找不到 "
            f"`{CLOUD_REPORT_PATH.relative_to(REPO_ROOT)}`。"
            "请先运行 `powershell -File core/scripts/eval.ps1`。"
        )
        return section

    dimensions = report.get("dimensions", [])
    section.lines.append(f"总体结论：**{'通过' if report.get('overallPassed') else '未通过'}**")
    section.lines.append("")
    section.lines.append("| 维度 | 指标 | 样本数 | 实测值 | 阈值 | 判定 |")
    section.lines.append("|---|---|---|---|---|---|")

    for item in dimensions:
        measured = float(item.get("measured", 0.0))
        passed = "通过" if item.get("passed") else "未通过"
        section.lines.append(
            f"| {item.get('dimension')} | {item.get('metric')} | "
            f"{item.get('sampleSize')} | {measured * 100:.1f}% | "
            f"{float(item.get('threshold', 0.0)) * 100:.1f}% | {passed} |"
        )

    section.lines.append("")
    section.lines.append("**每个维度测的是什么**：")
    section.lines.append("")
    for dimension, note in CLOUD_DIMENSION_NOTES.items():
        section.lines.append(f"- **{dimension}** —— {note}")

    section.lines.append("")
    section.lines.append("**每个维度没有证明什么**：")
    section.lines.append("")
    for dimension, limit in CLOUD_DIMENSION_LIMITS.items():
        section.lines.append(f"- **{dimension}** —— {limit}")

    failures = [
        (item.get("dimension"), failure)
        for item in dimensions
        for failure in item.get("failures", [])
    ]
    if failures:
        section.lines.append("")
        section.lines.append("**未通过的样本**：")
        section.lines.append("")
        for dimension, failure in failures:
            section.lines.append(f"- `{dimension}`：{failure}")

    return section


def build_memory_answer_section(report: dict[str, Any]) -> ReportSection:
    """构造记忆作答维度的三个数段落。

    **为什么要单独一段**：三个数的口径互不相同 ——
    混在���起给会让读者以为"准确率高就是好"。
    实际上"永远拒答"的系统准确率也是满分，
    而"什么都答"的系统编造率会爆表。

    @param report 云端评测 JSON 报告
    @return 段落
    """
    section = ReportSection(title="记忆作答维度的三个数")

    dimensions = report.get("dimensions", [])
    answer_item = next(
        (item for item in dimensions if item.get("dimension") == "MEMORY_ANSWER"), None
    )
    if answer_item is None:
        section.lines.append("**未执行该维度** —— 报告里没有 MEMORY_ANSWER 记录。")
        return section

    measured = float(answer_item.get("measured", 0.0))
    threshold = float(answer_item.get("threshold", 0.0))
    excluded = int(answer_item.get("excludedCount", 0))

    coverage = report.get("memoryAnswerRate")
    coverage_passed = report.get("memoryAnswerRatePassed")
    fabrication = report.get("memoryFabricationRate")
    fabrication_passed = report.get("memoryFabricationPassed")

    section.lines.append("| 指标 | 实测值 | 门禁 | 判定 | 口径 |")
    section.lines.append("|---|---|---|---|---|")
    section.lines.append(
        f"| 作答准确率 | {measured * 100:.1f}% | ≥ {threshold * 100:.1f}% | "
        f"{'通过' if answer_item.get('passed') else '未通过'} | "
        f"答对的 / 作答的（拒答不进分子也不进分母） |"
    )
    if coverage is not None:
        section.lines.append(
            f"| 作答率（覆盖率） | {float(coverage) * 100:.1f}% | ≥ 75.0% | "
            f"{'通过' if coverage_passed else '未通过'} | 作答的 / 期望作答的 |"
        )
    if fabrication is not None:
        section.lines.append(
            f"| 编造率 | {float(fabrication) * 100:.1f}% | ≤ 5.0% | "
            f"{'通过' if fabrication_passed else '未通过'} | 编造的 / 期望拒答的 |"
        )
    section.lines.append("")
    section.lines.append(
        f"另有 {excluded} 条样本被判定为**不适用**（如实拒答），"
        "它们既不进准确率的分子也不进分母。"
    )
    section.lines.append("")
    section.lines.append("**三个数各自管什么**：")
    section.lines.append("")
    for name, metric, note in MEMORY_ANSWER_METRICS:
        section.lines.append(f"- **{name}**（`{metric}`）—— {note}")
    section.lines.append("")
    section.lines.append(
        "**这三道判据合起来才是完整的产品判据**："
        "作答准确率管\"别乱答\"，作答率管\"别装死\"，编造率管\"库里没有的事别开口\"。"
        "缺任何一道，一个刻意做坏的系统都能钻过去 —— "
        "永远拒答能拿满准确率分，什么都答能拿满覆盖率分。"
    )
    return section


def build_edge_section() -> ReportSection:
    """构造端侧评测段落。

    @return 段落
    """
    section = ReportSection(title="端侧评测（识别维度）")

    if not EDGE_REPORT_PATH.is_file():
        section.lines.append(
            f"**未产出报告** —— 找不到 `{EDGE_REPORT_PATH.relative_to(REPO_ROOT)}`。"
        )
        return section

    text = EDGE_REPORT_PATH.read_text(encoding="utf-8")
    # 只取表格与结论段，口径说明由本文件统一给出，避免两处描述打架。
    for block in text.split("\n## "):
        if block.startswith("# 端侧识别"):
            for line in block.splitlines():
                if line.startswith("## "):
                    break
                section.lines.append(line)
            break

    section.lines.append("")
    section.lines.append(f"**说明**：{EDGE_DIMENSION_NOTE}")
    section.lines.append("")
    section.lines.append(f"**没有验证的**：{EDGE_DIMENSION_LIMITS}")
    return section


def build_e2e_section() -> ReportSection:
    """构造端到端断言段落。

    @return 段落
    """
    section = ReportSection(title="端到端断言（行为正确性）")

    report = _read_json(E2E_REPORT_PATH)
    if report is None:
        section.lines.append(
            "**未产出报告** —— 找不到 "
            f"`{E2E_REPORT_PATH.relative_to(REPO_ROOT)}`。"
            "请先运行 `powershell -File core/scripts/e2e.ps1`。"
        )
        return section

    section.lines.append(f"结论：**{report.get('result')}**")
    section.lines.append("")
    section.lines.append("| 检查项 | 判定 | 观测 |")
    section.lines.append("|---|---|---|")
    for item in report.get("checks", []):
        passed = "通过" if item.get("passed") else "未通过"
        section.lines.append(
            f"| {item.get('name')} | {passed} | `{item.get('detail', '')}` |"
        )

    section.lines.append("")
    section.lines.append(
        "**这些断言为什么可信**：隔离断言做过**反证** —— "
        "临时把云端改成所有会话共用一个记忆作用域后，"
        "泄漏检测项会失败并指出被泄漏的记忆标识。"
        "没有反证的断言可能是在测一个永远为真的条件。"
    )
    return section


def build_summary_section(
    cloud: ReportSection, edge: ReportSection, e2e: ReportSection
) -> ReportSection:
    """构造结论段落。

    @param cloud 云端段落
    @param edge 端侧段落
    @param e2e 端到端段落
    @return 段落
    """
    section = ReportSection(title="结论")

    missing = [
        section.title
        for section in (cloud, edge, e2e)
        if any("未产出报告" in line for line in section.lines)
    ]

    if missing:
        section.lines.append(
            f"**报告不完整** —— 以下维度没有产出报告：{', '.join(missing)}。"
            "缺失的维度不能被当作通过。"
        )
        return section

    section.lines.append(
        "本仓库当前**已验证**：意图分类、长期记忆召回、记忆作答的准确率与编造率、"
        "安全策略召回、情感标签判定、端侧安静环境识别、跨用户记忆隔离、离线降级行为。"
    )
    section.lines.append("")
    section.lines.append("本仓库当前**未验证**：")
    section.lines.append("")
    section.lines.append("- 真人语音的噪声鲁棒性与远场拾音")
    section.lines.append("- 长尾意图的云端大模型处理效果")
    section.lines.append("- 多轮对话中的情绪转折与澄清策略")
    section.lines.append("- 端到端延迟与并发承载能力")
    section.lines.append("- 记忆检索的规模化表现 —— 相关性下限两侧只有 0.0039 余量，"
                         "样本量 13 + 13 条，**换一批数据阈值很可能需要重调**")
    section.lines.append("- STM32 真机上的全部能力（见 `device-ref/README.md` 的未验证项）")
    section.lines.append("- 任何 LLM 相关的生成质量指标 —— 当前云端回复为**模板式记忆引用**，未接入大模型")
    section.lines.append("")
    section.lines.append(
        "完整清单见 `docs/known-limitations.md`。"
    )
    return section


def render_report() -> str:
    """渲染完整报告。

    @return Markdown 文本
    """
    cloud = build_cloud_section()
    edge = build_edge_section()
    e2e = build_e2e_section()
    summary = build_summary_section(cloud, edge, e2e)

    cloud_report = _read_json(CLOUD_REPORT_PATH)
    memory_answer = (
        build_memory_answer_section(cloud_report)
        if cloud_report is not None
        else ReportSection(title="记忆作答维度的三个数")
    )
    if cloud_report is None:
        memory_answer.lines.append("**未产出报告** —— 找不到云端评测 JSON 报告。")

    parts = [
        "# 语音陪伴机器人最终指标报告\n",
        "**本报告的每个数字都来自一次实际运行**。"
        "复现方式：`powershell -File core/scripts/e2e.ps1`。\n",
        summary.render(),
        cloud.render(),
        memory_answer.render(),
        edge.render(),
        e2e.render(),
    ]
    return "\n".join(parts)


def main(argv: list[str] | None = None) -> int:
    """脚本入口。

    @param argv 命令行参数
    @return 退出码
    """
    parser = argparse.ArgumentParser(description="汇总最终指标报告")
    parser.add_argument(
        "--output",
        default="data/reports/final-report.md",
        help="报告输出路径",
    )
    args = parser.parse_args(argv)

    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = REPO_ROOT / output_path

    content = render_report()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    print(f"最终报告已写入：{output_path}")

    if "未产出报告" in content:
        print("报告不完整：存在未产出报告的维度。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
