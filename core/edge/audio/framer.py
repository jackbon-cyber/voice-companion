"""音频帧组装。

设备时钟漂移与重采样边界会让送进来的音频块**不是整帧的整数倍**。
半帧若直接上行，云端按整帧解析就会造成音频时间轴错位，且没有任何错误信号。

本模块的职责：把任意长度的字节流切成**满帧**，末尾不足一帧的部分补齐到整帧
并显式标记 ``is_final_partial``，让云端知道这一帧是补出来的。

补齐用零填充 —— 补出来的尾部会被识别模型当作静音，能量判定自然不会把它
误认为有人声。
"""

from __future__ import annotations

from dataclasses import dataclass

from core.edge.audio.negotiation import frames_per_frame

# 16bit PCM 单声道的字节宽度。
BYTES_PER_SAMPLE = 2


@dataclass(frozen=True)
class Frame:
    """一帧待上行的音频。"""

    payload: bytes
    timestamp_ms: int
    is_final_partial: bool = False


class AudioFramer:
    """把连续字节流切成对齐的音频帧。"""

    def __init__(self, sample_rate: int, frame_duration_ms: int) -> None:
        """构造帧组装器。

        @param sample_rate 采样率（Hz）
        @param frame_duration_ms 帧长（毫秒）
        @throws ValueError 帧长非正时抛出
        """
        if frame_duration_ms <= 0:
            raise ValueError(f"帧长必须为正数，得到 {frame_duration_ms}")
        self._frame_bytes = frames_per_frame(sample_rate, frame_duration_ms) * BYTES_PER_SAMPLE
        self._frame_duration_ms = frame_duration_ms
        self._buffer = bytearray()
        self._emitted_frames = 0

    @property
    def frame_bytes(self) -> int:
        """整帧的字节数。

        @return 整帧字节数
        """
        return self._frame_bytes

    def push(self, chunk: bytes) -> list[Frame]:
        """送入一段音频字节，切出所有满帧。

        缓冲里不足一帧的余量会留着，等下一段来了一起切 —— 跨块边界的字节
        不能丢，丢了就是丢音频。

        @param chunk 音频字节
        @return 切出的满帧列表；末尾的半帧不在其中，等 {@link flush} 处理
        """
        self._buffer.extend(chunk)
        frames: list[Frame] = []
        while len(self._buffer) >= self._frame_bytes:
            payload = bytes(self._buffer[: self._frame_bytes])
            del self._buffer[: self._frame_bytes]
            frames.append(
                Frame(
                    payload=payload,
                    timestamp_ms=self._emitted_frames * self._frame_duration_ms,
                    is_final_partial=False,
                )
            )
            self._emitted_frames += 1
        return frames

    def flush(self) -> list[Frame]:
        """把缓冲里的余量补齐成整帧并交出。

        @return 补齐后的尾帧；缓冲为空时返回空列表
        """
        if not self._buffer:
            return []
        payload = bytes(self._buffer) + b"\x00" * (self._frame_bytes - len(self._buffer))
        self._buffer = bytearray()
        frame = Frame(
            payload=payload,
            timestamp_ms=self._emitted_frames * self._frame_duration_ms,
            is_final_partial=True,
        )
        self._emitted_frames += 1
        return [frame]
