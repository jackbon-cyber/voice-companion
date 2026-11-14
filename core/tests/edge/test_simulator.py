import json

import pytest

from core.edge.audio.negotiation import DEFAULT_FORMAT
from core.edge.degrade.policy import DegradeLevel
from core.edge.dialog.responder import LOCAL_SOURCE
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
    """云端连不上时模拟端不得崩溃：应降级并转入本地陪伴。"""
    simulator = EdgeSimulator(
        session_id="s-sim",
        cloud_url="ws://127.0.0.1:1/voice/uplink",
        phrases=["把音量调到五十"],
    )
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
    """端侧已处理的意图不再上行。

    上行会让云端多生成一条回复，而这条回复对应的是"我已经做完了"，
    用户会看到机器人答非所问地接话。
    """
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
    assert intents == []


@pytest.mark.asyncio
async def test_offline_run_produces_local_reply():
    """A7 验收：断开云端后，端侧仍能完成一轮本地应答。"""
    simulator = EdgeSimulator(
        session_id="s-offline",
        cloud_url="ws://127.0.0.1:1/voice/uplink",
        phrases=["今天好难过"],
    )
    await simulator.run(rounds=1)

    replies = simulator.local_replies
    assert replies, "离线时端侧必须仍能产生本地应答"
    assert all(reply.text for reply in replies)


@pytest.mark.asyncio
async def test_offline_run_degrades_to_offline_level():
    """连接失败应落到离线档，而不是停留在正常档假装一切正常。"""
    simulator = EdgeSimulator(
        session_id="s-offline",
        cloud_url="ws://127.0.0.1:1/voice/uplink",
        phrases=["今天好难过"],
    )
    await simulator.run(rounds=1)

    assert simulator.degrade_level() == DegradeLevel.OFFLINE
    assert simulator.is_offline is True


@pytest.mark.asyncio
async def test_offline_reply_is_marked_as_local_and_offline():
    """本地应答必须标记来源为本地、且标记处于离线档，不得伪装成云端回复。"""
    simulator = EdgeSimulator(
        session_id="s-offline",
        cloud_url="ws://127.0.0.1:1/voice/uplink",
        phrases=["今天好难过"],
    )
    await simulator.run(rounds=1)

    reply = simulator.local_replies[0]
    assert reply.source == LOCAL_SOURCE
    assert reply.locally_produced is True
    assert reply.offline is True


@pytest.mark.asyncio
async def test_offline_reply_uses_detected_emotion_bucket():
    """离线时也要按情感标签选话术，不能永远用默认桶。"""
    simulator = EdgeSimulator(
        session_id="s-offline",
        cloud_url="ws://127.0.0.1:1/voice/uplink",
        phrases=["今天好难过"],
    )
    await simulator.run(rounds=1)

    assert simulator.local_replies[0].emotion == "sadness"


@pytest.mark.asyncio
async def test_offline_factual_request_states_it_cannot_reach_network():
    """离线时的事实性请求必须说明自己查不了，不能编造也不能装作会回答。"""
    simulator = EdgeSimulator(
        session_id="s-offline",
        cloud_url="ws://127.0.0.1:1/voice/uplink",
        phrases=["今天天气怎么样"],
    )
    await simulator.run(rounds=1)

    reply = simulator.local_replies[0]
    assert reply.factual_guard is True
    assert "网络" in reply.text or "联网" in reply.text


@pytest.mark.asyncio
async def test_offline_run_does_not_raise():
    """离线运行不得抛出异常：设备在离线场景下等同于坏掉。"""
    simulator = EdgeSimulator(
        session_id="s-offline",
        cloud_url="ws://127.0.0.1:1/voice/uplink",
        phrases=["今天好难过"],
    )
    # 不加 pytest.raises：跑通本身就是断言。
    await simulator.run(rounds=2)
    assert len(simulator.local_replies) == 2
