import pytest
from jsonschema import Draft202012Validator

from core.protocol.loader import SCHEMA_NAMES, load_schema
from core.protocol.validator import build_validator


@pytest.mark.parametrize("name", SCHEMA_NAMES)
def test_every_schema_is_valid_draft_2020_12(name):
    schema = load_schema(name)
    Draft202012Validator.check_schema(schema)
    build_validator(name)


def test_audio_frame_requires_session_id_and_sequence():
    validator = build_validator("audio-frame")
    assert not validator.is_valid({"sessionId": "s1", "sequence": 0, "timestampMs": 0, "payloadBase64": "AAA="})
    assert validator.is_valid(
        {"sessionId": "s1", "sequence": 0, "timestampMs": 0, "sampleRate": 16000, "payloadBase64": "AAA="}
    )


def test_audio_frame_payload_is_base64_string():
    validator = build_validator("audio-frame")
    result = validator.is_valid(
        {"sessionId": "s1", "sequence": 0, "timestampMs": 0, "sampleRate": 16000, "payloadBase64": 123}
    )
    assert result is False
