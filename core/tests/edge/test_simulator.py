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


@pytest.mark.asyncio
async def test_factual_request_is_not_answered_locally(serve_echo):
    """事实性请求必须引导上云，端侧不得当作普通意图本地作答。"""
    received = []

    async def handler(connection):
        async for message in connection:
            received.append(message)

    async with serve_echo(handler) as base_url:
        simulator = EdgeSimulator(
            session_id="s-factual",
            cloud_url=base_url,
            phrases=["今天天气怎么样"],
        )
        await simulator.run(rounds=1)

    intents = [
        json.loads(message)
        for message in received
        if "intent" in message
    ]
    assert intents, "事实性请求也应当上行，由云端求证"
    assert all(item["handledLocally"] is False for item in intents)
    assert all(item["intent"] == "unknown" for item in intents)


@pytest.mark.asyncio
async def test_local_intent_is_not_sent_to_cloud(serve_echo):
    """端侧已处理的意图不再上行 —— 少一条上行就少一份延迟与费用。"""
    received = []

    async def handler(connection):
        async for message in connection:
            received.append(message)

    async with serve_echo(handler) as base_url:
        simulator = EdgeSimulator(
            session_id="s-local",
            cloud_url=base_url,
            phrases=["把音量调到五十"],
        )
        await simulator.run(rounds=1)

    intents = [json.loads(message) for message in received if "intent" in message]
    assert all(item["handledLocally"] is True for item in intents)
