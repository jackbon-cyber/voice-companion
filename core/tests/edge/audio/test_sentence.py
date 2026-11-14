from core.edge.audio.sentence import SentenceEvent, SentenceSegmenter, SentenceState


def test_tail_silence_ends_segment():
    segmenter = SentenceSegmenter(end_silence_ms=100, turn_silence_ms=500, frame_duration_ms=20)
    segmenter.feed(True)
    for _ in range(5):
        event = segmenter.feed(False)
    assert event.kind == "segment_end"


def test_long_silence_reports_turn_change():
    segmenter = SentenceSegmenter(end_silence_ms=100, turn_silence_ms=200, frame_duration_ms=20)
    segmenter.feed(True)
    for _ in range(10):
        event = segmenter.feed(False)
    assert event.kind == "turn_change"


def test_turn_change_discards_collected_frames():
    segmenter = SentenceSegmenter(end_silence_ms=100, turn_silence_ms=200, frame_duration_ms=20)
    segmenter.feed(True)
    for _ in range(10):
        event = segmenter.feed(False)
    assert event.frames == []


def test_segment_end_fires_only_once_during_continuous_silence():
    segmenter = SentenceSegmenter(end_silence_ms=100, turn_silence_ms=500, frame_duration_ms=20)
    segmenter.feed(True)
    events = [segmenter.feed(False) for _ in range(20)]
    segment_end_count = sum(1 for event in events if event.kind == "segment_end")
    assert segment_end_count == 1


def test_new_speech_re_arms_segment_end():
    segmenter = SentenceSegmenter(end_silence_ms=100, turn_silence_ms=500, frame_duration_ms=20)
    segmenter.feed(True)
    for _ in range(6):
        segmenter.feed(False)
    segmenter.feed(True)
    events = [segmenter.feed(False) for _ in range(6)]
    segment_end_count = sum(1 for event in events if event.kind == "segment_end")
    assert segment_end_count == 1


def test_turn_change_fires_after_segment_end():
    segmenter = SentenceSegmenter(end_silence_ms=100, turn_silence_ms=200, frame_duration_ms=20)
    segmenter.feed(True)
    events = [segmenter.feed(False) for _ in range(15)]
    kinds = [event.kind for event in events]
    assert "segment_end" in kinds
    assert "turn_change" in kinds
    assert kinds.index("turn_change") > kinds.index("segment_end")
