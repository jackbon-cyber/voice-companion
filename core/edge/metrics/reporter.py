"""端侧指标报告导出。

把 {@link MetricsCollector} 里的原始样本导出成**结构化报告**。报告要能
直接被评测门禁脚本读，也要能被人在几分钟内看懂 —— 所以同时产出 JSON
（给机器）与 Markdown（给人）。

报告的关键设计是**显式标注样本是否充足**：

- 样本数低于 ``MIN_SAMPLE_COUNT`` 的指标，其百分位**不具统计意义**；
  报告里必须标出来，而不是给出一个看起来很精确的数字。
- 样本数为 0 的指标**完全不出现在百分位表里**，但要在"缺失指标"里列出 ——
  区分"没测到"和"测了但没达标"是两回事。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.edge.metrics.collector import (
    DEFAULT_PERCENTILE,
    MIN_SAMPLE_COUNT,
    MetricsCollector,
    percentile,
)

# 报告里各指标的中文名与单位。
METRIC_LABELS: dict[str, tuple[str, str]] = {
    "vad": ("语音活动判定", "ms"),
    "asr": ("端侧识别", "ms"),
    "intent": ("意图判定", "ms"),
    "round_trip": ("上云往返", "ms"),
    "first_packet": ("首包延迟", "ms"),
}


@dataclass(frozen=True)
class MetricReport:
    """单个指标的报告条目。"""

    #: 指标标识。
    name: str
    #: 指标中文名。
    label: str
    #: 单位。
    unit: str
    #: 样本数。
    sample_count: int
    #: 中位数。
    median_ms: int
    #: 百分位（默认 P95）。
    percentile_ms: int
    #: 使用的分位。
    percentile_q: float
    #: 样本是否充足（达到 ``MIN_SAMPLE_COUNT``）。
    sufficient: bool

    def to_dict(self) -> dict[str, Any]:
        """转成可 JSON 序列化的字典。

        @return 字典
        """
        return {
            "name": self.name,
            "label": self.label,
            "unit": self.unit,
            "sampleCount": self.sample_count,
            "medianMs": self.median_ms,
            "percentileMs": self.percentile_ms,
            "percentileQ": self.percentile_q,
            "sufficient": self.sufficient,
        }


@dataclass
class MetricsReport:
    """一次端侧指标报告。"""

    #: 各指标的条目，按固定顺序排列。
    metrics: list[MetricReport] = field(default_factory=list)
    #: 完全没有样本的指标。
    missing_metrics: list[str] = field(default_factory=list)
    #: 生成报告时的环境信息。
    environment: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转成可 JSON 序列化的字典。

        @return 字典
        """
        return {
            "metrics": [metric.to_dict() for metric in self.metrics],
            "missingMetrics": list(self.missing_metrics),
            "environment": dict(self.environment),
        }

    def to_json(self, indent: int = 2) -> str:
        """导出为 JSON 文本。

        @param indent 缩进
        @return JSON 文本
        """
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def to_markdown(self) -> str:
        """导出为 Markdown 文本。

        @return Markdown 文本
        """
        lines: list[str] = ["# 端侧指标报告", ""]
        lines.append("| 指标 | 样本数 | 中位数 | P95 | 单位 | 样本是否充足 |")
        lines.append("|---|---|---|---|---|---|")
        for metric in self.metrics:
            lines.append(
                f"| {metric.label} | {metric.sample_count} | {metric.median_ms} | "
                f"{metric.percentile_ms} | {metric.unit} | "
                f"{'是' if metric.sufficient else '否'} |"
            )
        if self.missing_metrics:
            missing_labels = "、".join(
                METRIC_LABELS.get(name, (name, ""))[0] for name in self.missing_metrics
            )
            lines.append("")
            lines.append(f"**未采集到样本的指标**：{missing_labels}")
        if self.environment:
            lines.append("")
            lines.append("## 环境信息")
            lines.append("")
            for key in sorted(self.environment):
                lines.append(f"- {key}: {self.environment[key]}")
        return "\n".join(lines) + "\n"


class MetricsReporter:
    """把采集器导出成报告。"""

    def __init__(
        self,
        collector: MetricsCollector,
        min_sample_count: int = MIN_SAMPLE_COUNT,
        percentile_q: float = DEFAULT_PERCENTILE,
    ) -> None:
        """构造报告器。

        @param collector 采集器
        @param min_sample_count 样本充足阈值
        @param percentile_q 使用的分位
        @throws ValueError 阈值非正或分位越界时抛出
        """
        if min_sample_count <= 0:
            raise ValueError("样本充足阈值必须为正数")
        if not 0 < percentile_q <= 1:
            raise ValueError(f"分位必须落在 (0, 1]，得到 {percentile_q}")
        self._collector = collector
        self._min_sample_count = min_sample_count
        self._percentile_q = percentile_q

    def build(self, environment: dict[str, str] | None = None) -> MetricsReport:
        """生成报告。

        @param environment 环境信息
        @return 指标报告
        """
        snapshot = self._collector.snapshot()
        metrics: list[MetricReport] = []
        missing: list[str] = []

        for name, (label, unit) in METRIC_LABELS.items():
            sample_count = snapshot.sample_counts.get(name, 0)
            if sample_count == 0:
                missing.append(name)
                continue
            metrics.append(
                MetricReport(
                    name=name,
                    label=label,
                    unit=unit,
                    sample_count=sample_count,
                    median_ms=getattr(snapshot, f"{name}_ms"),
                    percentile_ms=self._percentile_of(name),
                    percentile_q=self._percentile_q,
                    sufficient=sample_count >= self._min_sample_count,
                )
            )

        return MetricsReport(
            metrics=metrics,
            missing_metrics=missing,
            environment=dict(environment or {}),
        )

    def _percentile_of(self, name: str) -> int:
        """取单个指标的百分位。

        @param name 指标标识
        @return 百分位值（毫秒）
        """
        samples = self._collector.samples_of(name)
        return percentile(samples, self._percentile_q)

    def export_json(self, path: Path, environment: dict[str, str] | None = None) -> MetricsReport:
        """导出 JSON 报告到文件。

        @param path 目标文件
        @param environment 环境信息
        @return 生成的报告
        """
        report = self.build(environment)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report.to_json(), encoding="utf-8")
        return report

    def export_markdown(
        self, path: Path, environment: dict[str, str] | None = None
    ) -> MetricsReport:
        """导出 Markdown 报告到文件。

        @param path 目标文件
        @param environment 环境信息
        @return 生成的报告
        """
        report = self.build(environment)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report.to_markdown(), encoding="utf-8")
        return report
