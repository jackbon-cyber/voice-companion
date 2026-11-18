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

from websockets.asyncio.client import connect

from core.edge.audio.framer import Frame
from core.edge.audio.negotiation import AudioFormat
from core.edge.intent.detector import IntentDecision
from core.edge.transport.downlink import DownlinkClient
from core.protocol.validator import validation_errors


class UplinkError(RuntimeError):
    """上行通道错误。

    继承 RuntimeError：上行失败是运行期链路问题，不是调用方用错了 API。
    """


class UplinkAuthError(UplinkError):
    """上行通道鉴权失败。

    与普通的 {@link UplinkError} 分开：鉴权失败是**配置问题**（凭据缺失或错误），
    不是网络问题。两者要分开处理 —— 网络断了可以降级到本地陪伴继续跑，
    而凭据错了必须让人知道"去改配置"，静默降级会把配置错误伪装成网络故障。
    """


class UplinkClient:
    """端侧上行通道客户端。"""

    def __init__(
        self,
        session_id: str,
        base_url: str,
        token: str | None = None,
        owner_key: str | None = None,
    ) -> None:
        """构造上行客户端。

        @param session_id 会话标识。**重连时必须保持不变**，否则云端会当作新会话。
        @param base_url WebSocket 服务地址
        @param token 接入凭据；为 None 时不带凭据（云端未启用鉴权时用）
        @param owner_key 会话归属的用户标识。云端据此绑定记忆作用域 ——
            没有它，云端写的记忆全部落进同一个作用域，跨用户隔离无从谈起。
        """
        self._session_id = session_id
        self._base_url = base_url
        self._token = token
        self._owner_key = owner_key
        self._sequence = 0
        self._format: AudioFormat | None = None
        self._connection: Any = None
        self._downlink = DownlinkClient(session_id)

    @property
    def session_id(self) -> str:
        """当前会话标识。

        @return 会话标识
        """
        return self._session_id

    @property
    def owner_key(self) -> str | None:
        """会话归属的用户标识。

        @return 用户标识；未设置时为 None
        """
        return self._owner_key

    @property
    def sequence(self) -> int:
        """下一个将使用的帧序号。

        @return 帧序号
        """
        return self._sequence

    async def connect(self, audio_format: AudioFormat) -> None:
        """建立上行连接并协商音频格式。

        @param audio_format 协商好的音频格式
        @throws UplinkAuthError 鉴权失败（握手被拒）时抛出
        @throws UplinkError 其他连接失败时抛出
        """
        self._format = audio_format
        try:
            self._connection = await connect(self._base_url, additional_headers=self._auth_headers())
        except Exception as error:
            raise self._classify_connect_error(error) from error

    async def reconnect(self, audio_format: AudioFormat | None = None) -> None:
        """重连，保留会话标识与序号。

        重连**不新建会话**：会话标识与帧序号都保留，云端据此把断线期间的
        上下文接上，而不是当作一次全新的对话。

        @param audio_format 音频格式；为 None 时沿用上次协商结果
        @throws UplinkAuthError 鉴权失败（握手被拒）时抛出
        @throws UplinkError 其他连接失败时抛出
        """
        if audio_format is not None:
            self._format = audio_format
        await self.close()
        try:
            self._connection = await connect(self._base_url, additional_headers=self._auth_headers())
        except Exception as error:
            raise self._classify_connect_error(error) from error

    def _classify_connect_error(self, error: Exception) -> UplinkError:
        """把连接异常分类成鉴权失败或普通连接失败。

        握手阶段被拒（HTTP 401 / 403）与"连不上"是两类问题：
        前者是凭据错，后者是网络不通。混为一谈会让配置错误被当成网络抖动，
        排查方向完全跑偏。

        @param error 原始异常
        @return 分类后的异常
        """
        status = self._handshake_status(error)
        if status in (401, 403):
            return UplinkAuthError(
                f"上行鉴权失败（HTTP {status}）：请检查 VOICE_UPLINK_TOKEN 是否正确"
            )
        return UplinkError(f"上行连接建立失败：{error}")

    def _handshake_status(self, error: Exception) -> int | None:
        """从握手异常里取 HTTP 状态码。

        websockets 15 的 {@code InvalidStatus} 把响应对象放在 {@code args[0]}，
        没有 {@code response} 属性；更早的版本用 {@code response}。
        两种形态都要认，否则升级 websockets 就会让鉴权失败被误判成网络失败。

        @param error 原始异常
        @return 状态码；取不到时返回 None
        """
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
        if isinstance(status, int):
            return status

        for argument in getattr(error, "args", ()):
            status = getattr(argument, "status_code", None)
            if isinstance(status, int):
                return status
        return None

    def _auth_headers(self) -> dict[str, str]:
        """构造鉴权请求头。

        凭据走请求头而不是查询参数：URL 会被记录进访问日志与代理日志，
        而请求头默认不会。查询参数形式只留给浏览器端（其 WebSocket API
        不能自定义请求头）。

        @return 请求头；无凭据时返回空字典
        """
        if not self._token:
            return {}
        return {"Authorization": f"Bearer {self._token}"}

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

    async def send_intent(self, decision: IntentDecision, text: str = "") -> None:
        """发送一条意图判定结果。

        @param decision 意图判定结果
        @param text 端侧识别出的用户原话。云端据此写入长期记忆并做召回 ——
            没有原话，云端只拿到意图标识，无法记住用户说过的话。
        @throws UplinkError 未连接或协议校验不通过时抛出
        """
        if self._connection is None:
            raise UplinkError("上行连接未建立，不能发送意图")
        message = {
            "sessionId": self._session_id,
            "sequence": self._sequence,
            "intent": decision.intent,
            "confidence": decision.confidence,
            "handledLocally": decision.handled_locally,
            "slots": decision.slots,
        }
        if text:
            message["text"] = text
        self._validate("intent-report", message)
        self._sequence += 1
        await self._connection.send(json.dumps(message, ensure_ascii=False))

    async def send_session_begin(self, audio_format: AudioFormat | None = None) -> None:
        """发送会话开始消息。

        会话开始必须**显式**发出而不是靠"发第一帧音频"隐含：
        云端要在收到音频之前就知道会话存在，才能提前建立会话上下文
        （粘滞路由、记忆装配都依赖这一步）。

        @param audio_format 协商好的音频格式；为 None 时沿用已协商结果
        @throws UplinkError 未连接或协议校验不通过时抛出
        """
        if self._connection is None:
            raise UplinkError("上行连接未建立，不能发送会话开始消息")
        negotiated = audio_format or self._format
        message: dict = {
            "sessionId": self._session_id,
            "type": "begin",
            "timestampMs": 0,
        }
        if negotiated is not None:
            message["audioFormat"] = negotiated.to_payload()
        if self._owner_key:
            message["ownerKey"] = self._owner_key
        self._validate("session", message)
        await self._connection.send(json.dumps(message, ensure_ascii=False))

    async def send_keepalive(self) -> None:
        """发送一次应用层心跳。

        心跳让云端能识别"设备还在但不说话"与"设备掉线"的区别：
        没有心跳时，云端只能靠 TCP 超时判断掉线，会把长时间的静默误判为离线，
        从而回收掉其实还活着的会话。

        @throws UplinkError 未连接或协议校验不通过时抛出
        """
        if self._connection is None:
            raise UplinkError("上行连接未建立，不能发送心跳")
        message = {
            "sessionId": self._session_id,
            "type": "keepalive",
            "timestampMs": 0,
        }
        self._validate("session", message)
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

    async def receive_downlink(self, now_ms: int) -> Any | None:
        """接收一条下行消息。

        上行与下行走**同一条连接**（WebSocket 是全双工的），因此下行消息
        从同一个连接上读。分派交给 {@code DownlinkClient}。

        @param now_ms 当前时间戳（毫秒），用于首包延迟测量
        @return 解析出的下行消息；连接已关闭或消息被丢弃时为 None
        """
        if self._connection is None:
            return None
        try:
            raw = await self._connection.recv()
        except Exception:
            # 连接关闭或读取失败：交给调用方决定是否重连。
            return None
        return self._downlink.handle_message(raw, now_ms)

    @property
    def downlink(self) -> DownlinkClient:
        """下行接收器。

        @return 下行接收器
        """
        return self._downlink

    def _validate(self, schema_name: str, payload: dict) -> None:
        """用协议 schema 校验一条上行消息。

        @param schema_name schema 名
        @param payload 消息载荷
        @throws UplinkError 校验不通过时抛出，消息里含被拒字段
        """
        errors = validation_errors(schema_name, payload)
        if errors:
            raise UplinkError(f"上行消息不符合 {schema_name} 协议，{errors[0]}")
