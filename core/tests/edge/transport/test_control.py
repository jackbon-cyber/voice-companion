import pytest

from core.edge.transport.control import PROFILE_DELTA_MAX_BYTES, ControlChannel


@pytest.mark.asyncio
async def test_profile_delta_within_limit_is_delivered():
    channel = ControlChannel(topic_prefix="voice/device")
    received = []

    async def callback(payload: bytes) -> None:
        received.append(payload)

    channel.on_profile_delta(callback)
    await channel.deliver_profile_delta(b"x" * 16)

    assert received == [b"x" * 16]


@pytest.mark.asyncio
async def test_profile_delta_exceeding_limit_is_rejected_not_truncated():
    channel = ControlChannel(topic_prefix="voice/device")
    received = []

    async def callback(payload: bytes) -> None:
        received.append(payload)

    channel.on_profile_delta(callback)
    await channel.deliver_profile_delta(b"x" * (PROFILE_DELTA_MAX_BYTES + 1))

    assert received == []
