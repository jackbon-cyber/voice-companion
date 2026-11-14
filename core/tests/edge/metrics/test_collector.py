from core.edge.metrics.collector import MIN_SAMPLE_COUNT, MetricsCollector


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
    from core.edge.metrics.collector import percentile

    samples = list(range(1, 101))
    assert percentile(samples, 0.95) == 95
    assert percentile(samples, 0.5) == 50


def test_percentile_of_empty_samples_is_zero():
    from core.edge.metrics.collector import percentile

    assert percentile([], 0.95) == 0
