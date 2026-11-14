"""音频格式协商。

协商失败必须**在发起任何网络请求之前**就拒绝，并把被拒的字段名带进错误信息：
协商是要跟云端反复协商的参数，带着一份云端不认的格式上去，只会在云端侧
以协议不符的方式失败，远不如在端侧当场说清"哪个参数不被支持"。

默认格式是 16kHz 单声道 16bit PCM —— 这是端侧 ASR 与云端嵌入模型
共同接受的窄带规格；Opus 只在弱网场景显式协商时启用。
"""

from __future__ import annotations

from dataclasses import dataclass

from core.protocol.loader import load_schema
from core.protocol.validator import validation_errors

# 协议里定义的编码方式名称。
ENCODING_PCM = "PCM_S16LE"
ENCODING_OPUS = "OPUS"

# 默认采样率（Hz）。窄带语音的通用规格，端侧 ASR 与云端嵌入都按此训练。
DEFAULT_SAMPLE_RATE = 16000

# 默认声道数。当前协议只支持单声道。
DEFAULT_CHANNELS = 1

# 默认位深。
DEFAULT_BIT_DEPTH = 16

# 默认帧长（毫秒）。20ms 是实时语音的常规取帧间隔。
DEFAULT_FRAME_DURATION_MS = 20


class NegotiationError(RuntimeError):
    """音频格式协商失败。

    继承 RuntimeException 而非 ValueError：协商失败是端云交互层面的
    运行期问题（对端要了一个我们不支持的格式），不是调用方用错了 API。
    """


@dataclass(frozen=True)
class AudioFormat:
    """一份协商好的音频格式。

    冻结是因为格式一旦协商完成就在一个会话内保持不变，
    允许修改会导致"上行帧格式"与"已协商格式"悄悄分叉。
    """

    sample_rate: int
    channels: int
    bit_depth: int
    encoding: str
    frame_duration_ms: int
    opus_bit_rate: int | None = None

    def to_payload(self) -> dict:
        """转成协议 ``audio-negotiation`` 的载荷形态。

        @return 可直接交给 JSON Schema 校验的字典
        """
        payload = {
            "sampleRate": self.sample_rate,
            "channels": self.channels,
            "bitDepth": self.bit_depth,
            "encoding": self.encoding,
            "frameDurationMs": self.frame_duration_ms,
        }
        if self.opus_bit_rate is not None:
            payload["opusBitRate"] = self.opus_bit_rate
        return payload


DEFAULT_FORMAT = AudioFormat(
    sample_rate=DEFAULT_SAMPLE_RATE,
    channels=DEFAULT_CHANNELS,
    bit_depth=DEFAULT_BIT_DEPTH,
    encoding=ENCODING_PCM,
    frame_duration_ms=DEFAULT_FRAME_DURATION_MS,
)


def frames_per_frame(sample_rate: int, frame_duration_ms: int) -> int:
    """按采样率与帧长算出单帧的采样点数。

    @param sample_rate 采样率（Hz）
    @param frame_duration_ms 帧长（毫秒）
    @return 单帧采样点数
    @throws ValueError 帧长非正时抛出
    """
    if frame_duration_ms <= 0:
        raise ValueError(f"frame duration must be positive, got {frame_duration_ms}")
    return sample_rate * frame_duration_ms // 1000


def negotiate(requested: dict | None) -> AudioFormat:
    """协商音频格式。

    请求可以只给出与默认不同的部分，未给出的项沿用默认格式 ——
    端侧设备通常只关心"我要换成 Opus"，不该被迫重复声明采样率与位深。

    @param requested 对端请求的格式字典；``None`` 表示对端未指定，走默认格式
    @return 协商结果
    @throws NegotiationError 请求的格式不被支持时抛出，消息中含被拒字段名
    """
    if requested is None:
        return DEFAULT_FORMAT

    # 先与默认格式合并再校验：schema 描述的是"完整的协商结果"，
    # 而请求允许只覆盖差异项。
    merged = DEFAULT_FORMAT.to_payload()
    merged.update(requested)

    validator_errors = validation_errors("audio-negotiation", merged)
    if validator_errors:
        raise NegotiationError(f"音频格式协商失败，{validator_errors[0]}")

    encoding = merged["encoding"]
    opus_bit_rate = merged.get("opusBitRate") if encoding == ENCODING_OPUS else None
    return AudioFormat(
        sample_rate=merged["sampleRate"],
        channels=merged["channels"],
        bit_depth=merged["bitDepth"],
        encoding=encoding,
        frame_duration_ms=merged["frameDurationMs"],
        opus_bit_rate=opus_bit_rate,
    )
