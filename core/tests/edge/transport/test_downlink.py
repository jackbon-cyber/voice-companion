import base64
import json

from core.edge.transport.downlink import DownlinkClient


def _voice_chunk(sequence: int, is_first: bool = False, is_last: bool = False) -> str:
    return json.dumps(
        {
            "sessionId": "s-1",
            "sequence": sequence,
            "payloadBase64": base64.b64encode(b"\x01\x02").decode("ascii"),
            "isFirst": is_first,
            "isLast": is_last,
        }
    )


def _text_reply(text: str = "我在呢") -> str:
    return json.dumps({"sessionId": "s-1", "text": text, "emotion": "tenderness"})


def test_voice_chunk_is_parsed():
    client = DownlinkClient("s-1")

    chunk = client.handle_message(_voice_chunk(0, is_first=True), now_ms=100)

    assert chunk is not None
    assert chunk.session_id == "s-1"
    assert chunk.sequence == 0
    assert chunk.payload == b"\x01\x02"
    assert chunk.is_first is True


def test_voice_chunk_completion_is_tracked():
    client = DownlinkClient("s-1")

    client.handle_message(_voice_chunk(0, is_first=True), now_ms=100)
    assert client.state.voice_completed is False

    client.handle_message(_voice_chunk(1, is_last=True), now_ms=110)
    assert client.state.voice_completed is True
    assert client.state.voice_chunk_count == 2


def test_text_reply_is_parsed():
    client = DownlinkClient("s-1")

    reply = client.handle_message(_text_reply(), now_ms=100)

    assert reply is not None
    assert reply.text == "我在呢"
    assert reply.emotion == "tenderness"
    assert client.state.last_text_reply is not None


def test_text_reply_with_citations_is_parsed():
    client = DownlinkClient("s-1")
    payload = json.dumps(
        {
            "sessionId": "s-1",
            "text": "你上次说喜欢清淡的",
            "emotion": "neutral",
            "citations": ["memory-1"],
        }
    )

    reply = client.handle_message(payload, now_ms=100)

    assert reply is not None
    assert reply.citations == ["memory-1"]


def test_invalid_json_is_dropped():
    client = DownlinkClient("s-1")

    assert client.handle_message("{not json", now_ms=100) is None
    assert client.state.dropped_count == 1


def test_unknown_message_shape_is_dropped():
    client = DownlinkClient("s-1")

    assert client.handle_message(json.dumps({"foo": "bar"}), now_ms=100) is None
    assert client.state.dropped_count == 1


def test_protocol_violation_is_dropped():
    """不合协议的下行消息不进业务逻辑。"""
    client = DownlinkClient("s-1")
    payload = json.dumps({"sessionId": "s-1", "sequence": 0, "payloadBase64": ""})

    assert client.handle_message(payload, now_ms=100) is None
    assert client.state.dropped_count == 1


def test_first_packet_latency_is_measured():
    client = DownlinkClient("s-1")

    client.handle_message(_voice_chunk(0, is_first=True), now_ms=250)

    assert client.first_packet_latency_ms(100) == 150


def test_first_packet_latency_is_none_before_first_chunk():
    client = DownlinkClient("s-1")

    assert client.first_packet_latency_ms(100) is None


def test_first_message_time_is_recorded():
    client = DownlinkClient("s-1")

    client.handle_message(_voice_chunk(0, is_first=True), now_ms=250)

    assert client.state.first_message_at_ms == 250
    assert client.state.first_chunk_at_ms == 250


def test_non_dict_payload_is_dropped():
    client = DownlinkClient("s-1")

    assert client.handle_message(json.dumps([1, 2, 3]), now_ms=100) is None
    assert client.state.dropped_count == 1
