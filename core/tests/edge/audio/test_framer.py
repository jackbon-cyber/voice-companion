import pytest

from core.edge.audio.framer import AudioFramer, Frame


def test_full_frame_is_emitted_without_padding():
    framer = AudioFramer(sample_rate=16000, frame_duration_ms=20)
    frames = framer.push(b"\x01" * 640)
    assert len(frames) == 1
    assert frames[0].is_final_partial is False
    assert len(frames[0].payload) == 640


def test_partial_tail_is_not_emitted_until_flush():
    framer = AudioFramer(sample_rate=16000, frame_duration_ms=20)
    framer.push(b"\x01" * 640)
    frames = framer.push(b"\x02" * 320)
    assert len(frames) == 0

    tail = framer.flush()
    assert len(tail) == 1
    assert tail[0].is_final_partial is True
    assert len(tail[0].payload) == 640


def test_buffer_spans_chunk_boundary_without_losing_bytes():
    framer = AudioFramer(sample_rate=16000, frame_duration_ms=20)
    frames = framer.push(b"\x01" * 400)
    assert frames == []
    frames = framer.push(b"\x02" * 400)
    assert len(frames) == 1
    assert len(frames[0].payload) == 640


def test_multiple_full_frames_are_emitted_at_once():
    framer = AudioFramer(sample_rate=16000, frame_duration_ms=20)
    frames = framer.push(b"\x01" * 1280)
    assert len(frames) == 2
    assert all(frame.is_final_partial is False for frame in frames)


def test_flush_emits_padded_remainder():
    framer = AudioFramer(sample_rate=16000, frame_duration_ms=20)
    framer.push(b"\x01" * 100)
    frames = framer.flush()
    assert len(frames) == 1
    assert frames[0].is_final_partial is True
    assert len(frames[0].payload) == 640


def test_flush_on_empty_buffer_emits_nothing():
    framer = AudioFramer(sample_rate=16000, frame_duration_ms=20)
    assert framer.flush() == []


def test_frame_length_follows_sample_rate():
    framer = AudioFramer(sample_rate=48000, frame_duration_ms=20)
    frames = framer.push(b"\x01" * 1920)
    assert len(frames) == 1
    assert len(frames[0].payload) == 1920


def test_invalid_frame_duration_is_rejected():
    with pytest.raises(ValueError):
        AudioFramer(sample_rate=16000, frame_duration_ms=0)


def test_frame_carries_timestamp_of_first_sample():
    framer = AudioFramer(sample_rate=16000, frame_duration_ms=20)
    frames = framer.push(b"\x01" * 640)
    assert frames[0].timestamp_ms == 0
    frames = framer.push(b"\x02" * 640)
    assert frames[0].timestamp_ms == 20
