import json

import pytest

from core.edge.audio.negotiation import DEFAULT_FORMAT
from core.edge.transport.uplink import UplinkClient


@pytest.mark.asyncio
async def test_audio_frames_are_sent_with_increasing_sequence(serve_echo):
    received = []

    async def handler(connection):
        async for message in connection:
            received.append(message)

    async with serve_echo(handler) as base_url:
        client = UplinkClient(session_id="s-1", base_url=base_url)
        await client.connect(DEFAULT_FORMAT)
        await client.send_audio_frame(b"\x01\x02", 0)
        await client.send_audio_frame(b"\x03\x04", 20)
        await client.close()

    sequences = [
        json.loads(message)["sequence"]
        for message in received
        if "payloadBase64" in message
    ]
    assert sequences == sorted(sequences)


@pytest.mark.asyncio
async def test_reconnect_keeps_session_id_and_continues_sequence(serve_echo):
    received = []

    async def handler(connection):
        async for message in connection:
            received.append(message)

    async with serve_echo(handler) as base_url:
        client = UplinkClient(session_id="s-1", base_url=base_url)
        await client.connect(DEFAULT_FORMAT)
        await client.send_audio_frame(b"\x01\x02", 0)

        await client.reconnect()
        await client.send_audio_frame(b"\x03\x04", 20)
        await client.close()

    assert client.session_id == "s-1"
    frames = [json.loads(message) for message in received if "payloadBase64" in message]
    assert [frame["sessionId"] for frame in frames] == ["s-1", "s-1"]
    assert [frame["sequence"] for frame in frames] == [0, 1]


@pytest.mark.asyncio
async def test_send_audio_frame_without_connection_is_rejected(serve_echo):
    from core.edge.transport.uplink import UplinkError

    async def handler(connection):
        async for _message in connection:
            pass

    async with serve_echo(handler) as base_url:
        client = UplinkClient(session_id="s-1", base_url=base_url)
        with pytest.raises(UplinkError):
            await client.send_audio_frame(b"\x01\x02", 0)


@pytest.mark.asyncio
async def test_final_partial_flag_is_carried_on_the_wire(serve_echo):
    received = []

    async def handler(connection):
        async for message in connection:
            received.append(message)

    async with serve_echo(handler) as base_url:
        client = UplinkClient(session_id="s-1", base_url=base_url)
        await client.connect(DEFAULT_FORMAT)
        await client.send_audio_frame(b"\x01\x02", 0, is_final_partial=True)
        await client.close()

    frame = json.loads(received[0])
    assert frame["isFinalPartial"] is True


@pytest.mark.asyncio
async def test_full_frame_carries_no_final_partial_flag(serve_echo):
    received = []

    async def handler(connection):
        async for message in connection:
            received.append(message)

    async with serve_echo(handler) as base_url:
        client = UplinkClient(session_id="s-1", base_url=base_url)
        await client.connect(DEFAULT_FORMAT)
        await client.send_audio_frame(b"\x01\x02", 0)
        await client.close()

    frame = json.loads(received[0])
    assert "isFinalPartial" not in frame


@pytest.mark.asyncio
async def test_send_frames_delivers_padded_tail_with_flag(serve_echo):
    from core.edge.audio.framer import AudioFramer

    received = []

    async def handler(connection):
        async for message in connection:
            received.append(message)

    async with serve_echo(handler) as base_url:
        client = UplinkClient(session_id="s-1", base_url=base_url)
        await client.connect(DEFAULT_FORMAT)
        framer = AudioFramer(sample_rate=16000, frame_duration_ms=20)
        framer.push(b"\x01" * 640)
        framer.push(b"\x02" * 320)
        await client.send_frames(framer.flush())
        await client.close()

    frame = json.loads(received[0])
    assert frame["isFinalPartial"] is True
    # 补齐后应为一整帧：320 采样点 × 2 字节。
    import base64

    assert len(base64.b64decode(frame["payloadBase64"])) == 640


@pytest.mark.asyncio
async def test_session_begin_carries_negotiated_audio_format(serve_echo):
    received = []

    async def handler(connection):
        async for message in connection:
            received.append(message)

    async with serve_echo(handler) as base_url:
        client = UplinkClient(session_id="s-1", base_url=base_url)
        await client.connect(DEFAULT_FORMAT)
        await client.send_session_begin()
        await client.close()

    message = json.loads(received[0])
    assert message["type"] == "begin"
    assert message["sessionId"] == "s-1"
    assert message["audioFormat"]["sampleRate"] == 16000
    assert message["audioFormat"]["frameDurationMs"] == 20


@pytest.mark.asyncio
async def test_keepalive_message_is_sent(serve_echo):
    received = []

    async def handler(connection):
        async for message in connection:
            received.append(message)

    async with serve_echo(handler) as base_url:
        client = UplinkClient(session_id="s-1", base_url=base_url)
        await client.connect(DEFAULT_FORMAT)
        await client.send_keepalive()
        await client.close()

    assert json.loads(received[0])["type"] == "keepalive"


@pytest.mark.asyncio
async def test_intent_report_passes_protocol_validation(serve_echo):
    from core.edge.intent.detector import IntentDecision

    received = []

    async def handler(connection):
        async for message in connection:
            received.append(message)

    async with serve_echo(handler) as base_url:
        client = UplinkClient(session_id="s-1", base_url=base_url)
        await client.connect(DEFAULT_FORMAT)
        await client.send_intent(IntentDecision("play_music", 0.9, {}, True))
        await client.close()

    message = json.loads(received[0])
    assert message["intent"] == "play_music"
    assert message["handledLocally"] is True
    assert "sequence" in message


@pytest.mark.asyncio
async def test_every_uplink_message_validates_against_a_schema(serve_echo):
    """上行消息必须能被协议 schema 校验 —— 云端要能校验每一条上行消息。"""
    from core.edge.intent.detector import IntentDecision
    from core.protocol.validator import build_validator

    received = []

    async def handler(connection):
        async for message in connection:
            received.append(message)

    async with serve_echo(handler) as base_url:
        client = UplinkClient(session_id="s-1", base_url=base_url)
        await client.connect(DEFAULT_FORMAT)
        await client.send_session_begin()
        await client.send_audio_frame(b"\x01\x02", 0)
        await client.send_intent(IntentDecision("play_music", 0.9, {}, True))
        await client.send_keepalive()
        await client.send_session_end("user_exit")
        await client.close()

    validators = {
        name: build_validator(name)
        for name in ("session", "audio-frame", "intent-report")
    }
    for raw in received:
        message = json.loads(raw)
        matched = [
            name for name, validator in validators.items() if validator.is_valid(message)
        ]
        assert matched, f"上行消息不属于任何协议 schema：{message}"
