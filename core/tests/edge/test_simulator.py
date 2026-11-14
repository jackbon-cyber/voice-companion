import json

import pytest

from core.edge.audio.negotiation import DEFAULT_FORMAT
from core.edge.simulator import EdgeSimulator


@pytest.mark.asyncio
async def test_simulator_sends_session_begin_and_end(serve_echo):
    received = []

    async def handler(connection):
        async for message in connection:
            received.append(message)

    async with serve_echo(handler) as base_url:
        simulator = EdgeSimulator(
            session_id="s-sim",
            cloud_url=base_url,
            phrases=["把音量调到五十"],
        )
        await simulator.run(rounds=1)

    kinds = [json.loads(message).get("type") for message in received]
    assert "begin" in kinds
    assert "end" in kinds


@pytest.mark.asyncio
async def test_simulator_uplinks_audio_frames(serve_echo):
    received = []

    async def handler(connection):
        async for message in connection:
            received.append(message)

    async with serve_echo(handler) as base_url:
        simulator = EdgeSimulator(
            session_id="s-sim",
            cloud_url=base_url,
            phrases=["把音量调到五十"],
        )
        await simulator.run(rounds=1)

    frames = [json.loads(message) for message in received if "payloadBase64" in message]
    assert frames, "模拟端应当上行音频帧"
    assert all(frame["sessionId"] == "s-sim" for frame in frames)


@pytest.mark.asyncio
async def test_simulator_survives_cloud_unreachable():
    simulator = EdgeSimulator(
        session_id="s-sim",
        cloud_url="ws://127.0.0.1:1/voice/uplink",
        phrases=["把音量调到五十"],
    )
    with pytest.raises(Exception):
        await simulator.run(rounds=1)
