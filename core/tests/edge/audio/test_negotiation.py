import pytest

from core.edge.audio.negotiation import (
    DEFAULT_FORMAT,
    NegotiationError,
    frames_per_frame,
    negotiate,
)


def test_absent_request_yields_default_pcm_format():
    resolved = negotiate(None)
    assert resolved.sample_rate == 16000
    assert resolved.channels == 1
    assert resolved.bit_depth == 16
    assert resolved.encoding == "PCM_S16LE"
    assert resolved.frame_duration_ms == 20


def test_opus_request_is_accepted_with_bit_rate():
    resolved = negotiate({"encoding": "OPUS", "opusBitRate": 24000})
    assert resolved.encoding == "OPUS"
    assert resolved.opus_bit_rate == 24000


def test_unsupported_encoding_is_rejected_with_reason():
    with pytest.raises(NegotiationError) as error:
        negotiate({"encoding": "MP3"})
    assert "MP3" in str(error.value)


def test_opus_without_bit_rate_is_rejected():
    with pytest.raises(NegotiationError) as error:
        negotiate({"encoding": "OPUS"})
    assert "opusBitRate" in str(error.value)


def test_frame_length_is_derived_from_sample_rate():
    assert frames_per_frame(16000, 20) == 320
    assert frames_per_frame(48000, 20) == 960


def test_default_format_is_pcm():
    assert DEFAULT_FORMAT.encoding == "PCM_S16LE"
