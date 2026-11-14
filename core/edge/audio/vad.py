"""端侧语音活动检测。

采用**双重判定**：只有「语音概率达标」**且**「底噪能量达标」才判有人声。

只用能量会被键盘声、空调声、纸张声误触发；只用语音概率在极安静环境下
会因模型对静音的误判而误触发。两者取交集能显著压低误触发率 ——
代价是安静环境下的轻声说话可能漏检，这是可接受的取舍：漏检只是让这一句
不被识别，而误触发会让端侧在用户没说话时反复起播。
"""

from __future__ import annotations

import math
from array import array

# 默认语音概率阈值。
DEFAULT_SPEECH_PROBABILITY_THRESHOLD = 0.6

# 默认底噪能量阈值（归一化 RMS）。
DEFAULT_ENERGY_THRESHOLD = 0.01

# 16bit 采样的字节宽度。
SAMPLE_WIDTH = 2

# 16bit 有符号采样的满量程。
FULL_SCALE = 32768.0


class VoiceActivityDetector:
    """基于语音概率与底噪能量的双重判定器。"""

    def __init__(
        self,
        speech_probability_threshold: float = DEFAULT_SPEECH_PROBABILITY_THRESHOLD,
        energy_threshold: float = DEFAULT_ENERGY_THRESHOLD,
    ) -> None:
        """构造检测器。

        @param speech_probability_threshold 语音概率阈值
        @param energy_threshold 底噪能量阈值（归一化 RMS）
        """
        self._speech_probability_threshold = speech_probability_threshold
        self._energy_threshold = energy_threshold

    def is_speech(self, probability: float, energy: float) -> bool:
        """判定一帧是否有人声。

        @param probability 语音概率
        @param energy 底噪能量（归一化 RMS）
        @return 有人声返回 True
        """
        return (
            probability >= self._speech_probability_threshold
            and energy >= self._energy_threshold
        )

    def is_speech_frame(self, frame: bytes) -> bool:
        """直接对一帧 PCM 做能量判定。

        供没有语音概率模型的降级路径使用（例如模型缺失时只靠能量兜底）。

        @param frame 一帧 PCM 字节
        @return 能量达标返回 True
        @throws ValueError 帧长度不是 16bit 采样的整数倍时抛出
        """
        if len(frame) % SAMPLE_WIDTH != 0:
            raise ValueError(f"PCM 帧长度必须是 {SAMPLE_WIDTH} 的倍数，得到 {len(frame)}")
        if not frame:
            return False
        return self.frame_energy(frame) >= self._energy_threshold

    def frame_energy(self, frame: bytes) -> float:
        """计算一帧 PCM 的归一化 RMS 能量。

        @param frame 一帧 PCM 字节
        @return 归一化 RMS，取值区间 [0, 1]
        @throws ValueError 帧长度不是 16bit 采样的整数倍时抛出
        """
        if len(frame) % SAMPLE_WIDTH != 0:
            raise ValueError(f"PCM 帧长度必须是 {SAMPLE_WIDTH} 的倍数，得到 {len(frame)}")
        if not frame:
            return 0.0
        samples = array("h")
        samples.frombytes(frame)
        if not samples:
            return 0.0
        total = sum(sample * sample for sample in samples)
        return math.sqrt(total / len(samples)) / FULL_SCALE
