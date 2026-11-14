import pytest

from core.edge.metrics.collector import MIN_SAMPLE_COUNT, MetricsCollector, percentile


def test_snapshot_reports_median_and_p95():
    collector = MetricsCollector()
    for value in range(1, 101):
        collector.record_first_packet(value)
    timings = collector.snapshot()
    assert timings.first_packet_ms == 50
    assert timings.sample_count == 100


def test_snapshot_marks_insufficient_samples():
    collector = MetricsCollector()
    collector.record_first_packet(120)
    timings = collector.snapshot()
    assert timings.sample_count < MIN_SAMPLE_COUNT


def test_snapshot_on_empty_collector_returns_zeroes():
    collector = MetricsCollector()
    timings = collector.snapshot()
    assert timings.first_packet_ms == 0
    assert timings.sample_count == 0


def test_percentile_uses_nearest_rank():
    samples = list(range(1, 101))
    assert percentile(samples, 0.95) == 95
    assert percentile(samples, 0.5) == 50


def test_percentile_of_empty_samples_is_zero():
    assert percentile([], 0.95) == 0


def test_snapshot_reports_per_metric_sample_counts():
    """各指标样本数通常不等，门禁要能分辨是哪一个不足。"""
    collector = MetricsCollector()
    collector.record_vad(10)
    collector.record_vad(12)
    collector.record_asr(30)

    snapshot = collector.snapshot()

    assert snapshot.sample_counts["vad"] == 2
    assert snapshot.sample_counts["asr"] == 1
    assert snapshot.sample_counts["first_packet"] == 0


def test_sample_count_is_conservative_minimum():
    """只有 vad 与 asr 有样本时，整体样本数取最小值 1。"""
    collector = MetricsCollector()
    for _ in range(5):
        collector.record_vad(10)
    collector.record_asr(30)

    snapshot = collector.snapshot()

    assert snapshot.sample_count == 1


def test_sample_count_reflects_all_metrics_being_populated():
    collector = MetricsCollector()
    for _ in range(7):
        collector.record_vad(10)
        collector.record_asr(30)
        collector.record_intent(2)
        collector.record_round_trip(120)
        collector.record_first_packet(80)

    snapshot = collector.snapshot()

    assert snapshot.sample_count == 7
