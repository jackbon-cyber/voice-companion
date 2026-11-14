import json

import pytest

from core.edge.metrics.collector import MetricsCollector
from core.edge.metrics.reporter import METRIC_LABELS, MetricsReporter


def _collector_with_samples(count: int = 100) -> MetricsCollector:
    collector = MetricsCollector()
    for value in range(1, count + 1):
        collector.record_vad(value)
        collector.record_asr(value * 2)
        collector.record_intent(value * 3)
        collector.record_round_trip(value * 4)
        collector.record_first_packet(value * 5)
    return collector


def test_report_contains_all_five_stages():
    reporter = MetricsReporter(_collector_with_samples())

    report = reporter.build()

    names = {metric.name for metric in report.metrics}
    assert names == set(METRIC_LABELS)


def test_report_contains_each_stage_field():
    """报告结构必须包含各阶段字段 —— 这是评测脚本的输入契约。"""
    reporter = MetricsReporter(_collector_with_samples())

    report = reporter.build()
    payload = report.to_dict()

    for metric in payload["metrics"]:
        assert {"name", "label", "unit", "sampleCount", "medianMs", "percentileMs"} <= set(metric)


def test_report_marks_insufficient_samples():
    reporter = MetricsReporter(_collector_with_samples(count=10), min_sample_count=100)

    report = reporter.build()

    assert all(metric.sufficient is False for metric in report.metrics)


def test_report_marks_sufficient_samples():
    reporter = MetricsReporter(_collector_with_samples(count=100), min_sample_count=100)

    report = reporter.build()

    assert all(metric.sufficient is True for metric in report.metrics)


def test_missing_metric_is_listed_separately():
    """没测到的指标要单独列出 —— 区分"没测"和"没达标"。"""
    collector = MetricsCollector()
    collector.record_vad(10)
    reporter = MetricsReporter(collector)

    report = reporter.build()

    assert report.missing_metrics == ["asr", "intent", "round_trip", "first_packet"]
    assert [metric.name for metric in report.metrics] == ["vad"]


def test_report_percentile_is_nearest_rank():
    reporter = MetricsReporter(_collector_with_samples(count=100))

    report = reporter.build()
    vad = next(metric for metric in report.metrics if metric.name == "vad")

    assert vad.percentile_ms == 95
    assert vad.median_ms == 50


def test_json_export_is_valid_json():
    reporter = MetricsReporter(_collector_with_samples())

    payload = json.loads(reporter.build().to_json())

    assert "metrics" in payload
    assert "missingMetrics" in payload


def test_markdown_export_contains_table():
    reporter = MetricsReporter(_collector_with_samples())

    text = reporter.build().to_markdown()

    assert "| 指标 |" in text
    assert "首包延迟" in text


def test_markdown_export_lists_missing_metrics():
    collector = MetricsCollector()
    collector.record_vad(10)

    text = MetricsReporter(collector).build().to_markdown()

    assert "未采集到样本的指标" in text


def test_export_writes_files(tmp_path):
    collector = _collector_with_samples()
    reporter = MetricsReporter(collector)

    reporter.export_json(tmp_path / "report.json", {"python": "3.13"})
    reporter.export_markdown(tmp_path / "report.md", {"python": "3.13"})

    assert (tmp_path / "report.json").exists()
    assert (tmp_path / "report.md").exists()
    assert "python" in (tmp_path / "report.json").read_text(encoding="utf-8")


def test_environment_is_included_in_report():
    reporter = MetricsReporter(_collector_with_samples())

    report = reporter.build({"os": "Windows", "python": "3.13.7"})

    assert report.environment["os"] == "Windows"


def test_invalid_percentile_raises():
    collector = MetricsCollector()
    with pytest.raises(ValueError):
        MetricsReporter(collector, percentile_q=0)
    with pytest.raises(ValueError):
        MetricsReporter(collector, percentile_q=1.5)


def test_invalid_min_sample_count_raises():
    with pytest.raises(ValueError):
        MetricsReporter(MetricsCollector(), min_sample_count=0)


def test_samples_of_unknown_metric_raises():
    with pytest.raises(ValueError):
        MetricsCollector().samples_of("unknown")
