"""端侧下行通道客户端。

下行与上行是**两个方向**，职责也不同，因此分成两个模块而不是塞进
``UplinkClient``：

- 上行：端侧是发送方，每条消息都要发出去，失败要重试；
- 下行：端侧是接收方，消息是**异步到达**的，收到后要按类型分派。

下行消息**先校验再分派**：不合协议的消息直接丢弃并计数，
不进业务逻辑 —— 一条坏消息不该让端侧的处理流程走偏。
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field

from core.protocol.validator import validation_errors


class DownlinkError(RuntimeError):
    """下行通道错误。

    继承 RuntimeError：下行失败是运行期链路问题，不是调用方用错了 API。
    """


@dataclass(frozen=True)
class VoiceChunk:
    """一条下行语音片段。"""

    session_id: str
    sequence: int
    payload: bytes
    is_first: bool = False
    is_last: bool = False
    emotion: str | None = None


@dataclass(frozen=True)
class TextReply:
    """一条下行文本回复。"""

    session_id: str
    text: str
    emotion: str
    citations: list[str] = field(default_factory=list)


@dataclass
class DownlinkState:
    """下行接收状态。"""

    voice_chunk_count: int = 0
    received_first_chunk: bool = False
    voice_completed: bool = False
    last_text_reply: TextReply | None = None
    dropped_count: int = 0
    first_message_at_ms: int | None = None
    first_chunk_at_ms: int | None = None


class DownlinkClient:
    """端侧下行通道接收器。"""

    def __init__(self, session_id: str) -> None:
        self._session_id = session_id
        self._state = DownlinkState()

    @property
    def state(self) -> DownlinkState:
        return self._state

    def handle_message(self, raw: str, now_ms: int) -> VoiceChunk | TextReply | None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            self._state.dropped_count += 1
            return None

        if not isinstance(payload, dict):
            self._state.dropped_count += 1
            return None

        if "payloadBase64" in payload:
            return self._handle_voice_chunk(payload, now_ms)
        if "text" in payload:
            return self._handle_text_reply(payload)
        self._state.dropped_count += 1
        return None

    def _handle_voice_chunk(self, payload: dict, now_ms: int) -> VoiceChunk | None:
        errors = validation_errors("voice-chunk", payload)
        if errors:
            self._state.dropped_count += 1
            return None

        if self._state.first_message_at_ms is None:
            self._state.first_message_at_ms = now_ms

        is_first = bool(payload.get("isFirst", False))
        if is_first and self._state.first_chunk_at_ms is None:
            self._state.first_chunk_at_ms = now_ms

        chunk = VoiceChunk(
            session_id=payload["sessionId"],
            sequence=payload["sequence"],
            payload=base64.b64decode(payload["payloadBase64"]),
            is_first=is_first,
            is_last=bool(payload.get("isLast", False)),
            emotion=payload.get("emotion"),
        )
        self._state.voice_chunk_count += 1
        self._state.received_first_chunk = self._state.received_first_chunk or is_first
        if chunk.is_last:
            self._state.voice_completed = True
        return chunk

    def _handle_text_reply(self, payload: dict) -> TextReply | None:
        errors = validation_errors("text-reply", payload)
        if errors:
            self._state.dropped_count += 1
            return None

        reply = TextReply(
            session_id=payload["sessionId"],
            text=payload["text"],
            emotion=payload["emotion"],
            citations=list(payload.get("citations", [])),
        )
        self._state.last_text_reply = reply
        return reply

    def first_packet_latency_ms(self, request_sent_at_ms: int) -> int | None:
        if self._state.first_chunk_at_ms is None:
            return None
        return self._state.first_chunk_at_ms - request_sent_at_ms
