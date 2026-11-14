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
