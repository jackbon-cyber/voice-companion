import json

import pytest

from core.edge.metrics.collector import MetricsCollector
from core.edge.metrics.reporter import MetricsReporter


def test_generation_speed_is_tokens_per_second():
    """生成速度以「每秒生成 token 数」计量，而不是毫秒。

    毫秒只能说明"这次生成花了多久"，说明不了"模型有多快"——
    生成 5 个字花 100 毫秒与生成 50 个字花 100 毫秒是两种完全不同的能力。
    """
    collector = MetricsCollector()
    collector.record_generation(micros=500_000, tokens=50)

    snapshot = collector.snapshot()

    # 0.5 秒生成 50 token → 100 token/s
    assert snapshot.generation_tokens_per_second == 100.0
    assert snapshot.sample_counts["generation"] == 1


def test_generation_speed_is_zero_without_samples():
    collector = MetricsCollector()

    snapshot = collector.snapshot()

    assert snapshot.generation_tokens_per_second == 0
    assert snapshot.sample_counts["generation"] == 0


def test_generation_speed_ignores_zero_token_samples():
    """生成 0 个 token 时速度无意义，不应参与平均值计算。"""
    collector = MetricsCollector()
    collector.record_generation(micros=100_000, tokens=0)
    collector.record_generation(micros=500_000, tokens=50)

    snapshot = collector.snapshot()

    assert snapshot.generation_tokens_per_second == 100.0


def test_confidence_distribution_is_reported():
    """置信度分布要给出分桶统计，而不是只有一个平均值。

    平均置信度会掩盖"绝大多数很自信、少数极不自信"这种关键形态 ——
    后者恰恰是拒识机制要拦下的部分。
    """
    collector = MetricsCollector()
    for value in (0.95, 0.92, 0.85, 0.40):
        collector.record_confidence(value)

    snapshot = collector.snapshot()

    assert snapshot.sample_counts["confidence"] == 4
    assert snapshot.confidence_high == 2
    assert snapshot.confidence_medium == 1
    assert snapshot.confidence_low == 1


def test_confidence_buckets_use_fixed_thresholds():
    """分桶阈值必须固定且写死，不能随样本自适应。"""
    collector = MetricsCollector()
    for value in (0.99, 0.90, 0.89, 0.70, 0.69, 0.30, 0.0):
        collector.record_confidence(value)

    snapshot = collector.snapshot()

    # 高: >=0.9 → 0.99, 0.90；中: [0.7,0.9) → 0.89, 0.70；低: <0.7 → 0.69, 0.30, 0.0
    assert snapshot.confidence_high == 2
    assert snapshot.confidence_medium == 2
    assert snapshot.confidence_low == 3


def test_confidence_out_of_range_is_rejected():
    collector = MetricsCollector()

    with pytest.raises(ValueError):
        collector.record_confidence(1.5)

    with pytest.raises(ValueError):
        collector.record_confidence(-0.1)


def test_reporter_includes_generation_metric():
    collector = MetricsCollector()
    collector.record_generation(micros=500_000, tokens=50)

    report = MetricsReporter(collector).build()

    names = {metric.name for metric in report.metrics}
    assert "generation" in names


def test_reporter_includes_confidence_distribution():
    """置信度是分布，不是标量，因此单独成节而不是塞进指标表。"""
    collector = MetricsCollector()
    collector.record_confidence(0.95)
    collector.record_confidence(0.30)

    report = MetricsReporter(collector).build()

    assert report.confidence_distribution is not None
    assert report.confidence_distribution["sample_count"] == 2
    assert report.confidence_distribution["high"] == 1
    assert report.confidence_distribution["low"] == 1


def test_reporter_marks_confidence_missing_when_no_sample():
    collector = MetricsCollector()

    report = MetricsReporter(collector).build()

    assert report.confidence_distribution is None
    assert "confidence" in report.missing_metrics
