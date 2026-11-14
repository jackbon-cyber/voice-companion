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
