"""端侧上行通道客户端。

上行通道承载音频帧与意图消息。两条关键设计：

1. **序号由客户端实例维护**，重连时从断点续传。若把序号放在服务端或
   每次重连重新计数，云端会收到序号回退的帧，无法判断是丢帧还是重传。
2. **发帧前用协议 schema 校验**。协议不匹配的帧在端侧就被拦下并带上
   被拒字段名，比在云端看到一条含糊的"协议错误"更容易定位。
"""

from __future__ import annotations

import base64
import json
from typing import Any

from jsonschema import Draft202012Validator
from websockets.asyncio.client import connect

from core.edge.audio.framer import Frame
from core.edge.audio.negotiation import AudioFormat
from core.edge.intent.detector import IntentDecision
from core.protocol.loader import load_schema


class UplinkError(RuntimeError):
    """上行通道错误。

    继承 RuntimeError：上行失败是运行期链路问题，不是调用方用错了 API。
    """


class UplinkClient:
    """端侧上行通道客户端。"""

    def __init__(self, session_id: str, base_url: str) -> None:
        """构造上行客户端。

        @param session_id 会话标识。**重连时必须保持不变**，否则云端会当作新会话。
        @param base_url WebSocket 服务地址
        """
        self._session_id = session_id
        self._base_url = base_url
        self._sequence = 0
        self._format: AudioFormat | None = None
        self._connection: Any = None

    @property
    def session_id(self) -> str:
        """当前会话标识。

        @return 会话标识
        """
        return self._session_id

    @property
    def sequence(self) -> int:
        """下一个将使用的帧序号。

        @return 帧序号
        """
        return self._sequence

    async def connect(self, audio_format: AudioFormat) -> None:
        """建立上行连接并协商音频格式。

        @param audio_format 协商好的音频格式
        @throws UplinkError 连接失败时抛出
        """
        self._format = audio_format
        try:
            self._connection = await connect(self._base_url)
        except Exception as error:
            raise UplinkError(f"上行连接建立失败：{error}") from error

    async def reconnect(self, audio_format: AudioFormat | None = None) -> None:
        """重连，保留会话标识与序号。

        重连**不新建会话**：会话标识与帧序号都保留，云端据此把断线期间的
        上下文接上，而不是当作一次全新的对话。

        @param audio_format 音频格式；为 None 时沿用上次协商结果
        @throws UplinkError 重连失败时抛出
        """
        if audio_format is not None:
            self._format = audio_format
        await self.close()
        try:
            self._connection = await connect(self._base_url)
        except Exception as error:
            raise UplinkError(f"上行重连失败：{error}") from error

    async def send_audio_frame(
        self,
        payload: bytes,
        timestamp_ms: int,
        is_final_partial: bool = False,
    ) -> None:
        """发送一帧音频。

        @param payload 一帧 PCM 或 Opus 负载，必须是对齐的整帧
        @param timestamp_ms 该帧首采样点的会话内相对毫秒偏移
        @param is_final_partial 该帧是否由不足一帧的尾部补齐而来
        @throws UplinkError 未连接、格式未协商或协议校验不通过时抛出
        """
        if self._connection is None:
            raise UplinkError("上行连接未建立，不能发送音频帧")
        if self._format is None:
            raise UplinkError("音频格式尚未协商，不能发送音频帧")

        frame = {
            "sessionId": self._session_id,
            "sequence": self._sequence,
            "timestampMs": timestamp_ms,
            "sampleRate": self._format.sample_rate,
            "payloadBase64": base64.b64encode(payload).decode("ascii"),
        }
        if is_final_partial:
            # 补齐标记必须上行：云端据此知道这一帧尾部是补出来的零，
            # 不会把它当成真实音频参与端点检测。
            frame["isFinalPartial"] = True
        self._validate("audio-frame", frame)

        self._sequence += 1
        await self._connection.send(json.dumps(frame, ensure_ascii=False))

    async def send_frames(self, frames: list[Frame]) -> None:
        """批量发送音频帧。

        @param frames 待发送的帧
        @throws UplinkError 未连接或协议校验不通过时抛出
        """
        for frame in frames:
            await self.send_audio_frame(
                frame.payload,
                frame.timestamp_ms,
                is_final_partial=frame.is_final_partial,
            )

    async def send_intent(self, decision: IntentDecision) -> None:
        """发送一条意图判定结果。

        @param decision 意图判定结果
        @throws UplinkError 未连接时抛出
        """
        if self._connection is None:
            raise UplinkError("上行连接未建立，不能发送意图")
        message = {
            "sessionId": self._session_id,
            "intent": decision.intent,
            "confidence": decision.confidence,
            "handledLocally": decision.handled_locally,
            "slots": decision.slots,
        }
        await self._connection.send(json.dumps(message, ensure_ascii=False))

    async def send_session_end(self, reason: str) -> None:
        """发送会话结束消息。

        @param reason 结束原因
        @throws UplinkError 未连接时抛出
        """
        if self._connection is None:
            raise UplinkError("上行连接未建立，不能发送会话结束消息")
        message = {
            "sessionId": self._session_id,
            "type": "end",
            "reason": reason,
        }
        self._validate("session", message)
        await self._connection.send(json.dumps(message, ensure_ascii=False))

    async def close(self) -> None:
        """关闭上行连接。

        关闭失败不抛出：连接可能已经断了，清理动作不应盖掉真正的错误。
        """
        if self._connection is None:
            return
        try:
            await self._connection.close()
        except Exception:
            pass
        finally:
            self._connection = None

    def _validate(self, schema_name: str, payload: dict) -> None:
        """用协议 schema 校验一条上行消息。

        @param schema_name schema 名
        @param payload 消息载荷
        @throws UplinkError 校验不通过时抛出，消息里含被拒字段
        """
        validator = Draft202012Validator(load_schema(schema_name))
        errors = sorted(validator.iter_errors(payload), key=lambda error: list(error.absolute_path))
        if not errors:
            return
        first = errors[0]
        field = ".".join(str(part) for part in first.absolute_path) or "(根)"
        raise UplinkError(f"上行消息不符合 {schema_name} 协议，字段 {field}：{first.message}")
