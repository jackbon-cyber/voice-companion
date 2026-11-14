"""端侧断句状态机。

两种静音结局，语义完全不同：

- **句末静音**（较短）—— 用户说完了这句话。把已收集的音频交出去识别。
- **换人静音**（较长）—— 用户停下来走了，之前的半句作废。丢弃已收集的音频。

如果把换人也当成句末送出去，识别会得到一段被截断的话，用户会听到机器人
把别人的话当成自己说的复述一遍；反过来把句末一律丢弃，用户每说一句都会被
系统吞掉。

静音计时在 ``segment_end`` 之后**继续累计** —— 否则一旦先达到句末阈值并交出
片段，后续的静音就重新开始计时，换人阈值永远到不了。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# 事件类型：本次喂入没有产生任何状态变化。
EVENT_NONE = "none"

# 事件类型：检测到句末，收集的音频应交给识别。
EVENT_SEGMENT_END = "segment_end"

# 事件类型：检测到换人，收集的音频应丢弃。
EVENT_TURN_CHANGE = "turn_change"

# 默认句末静音阈值（毫秒）。
DEFAULT_END_SILENCE_MS = 600

# 默认换人静音阈值（毫秒）。
DEFAULT_TURN_SILENCE_MS = 2000

# 默认帧长（毫秒）。
DEFAULT_FRAME_DURATION_MS = 20


class SentenceState(Enum):
    """断句状态机的状态。"""

    IDLE = "IDLE"
    SPEAKING = "SPEAKING"
    SILENCE = "SILENCE"


@dataclass
class SentenceEvent:
    """一次喂入产生的结果。

    ``frames`` 在 ``segment_end`` 时是待识别的音频，在 ``turn_change`` 时为空
    （换人场景下已收集的音频被丢弃）。
    """

    kind: str = EVENT_NONE
    frames: list[bytes] = field(default_factory=list)


class SentenceSegmenter:
    """把连续的帧流切成一个个语句段。"""

    def __init__(
        self,
        end_silence_ms: int = DEFAULT_END_SILENCE_MS,
        turn_silence_ms: int = DEFAULT_TURN_SILENCE_MS,
        frame_duration_ms: int = DEFAULT_FRAME_DURATION_MS,
    ) -> None:
        """构造断句器。

        @param end_silence_ms 句末静音阈值（毫秒）
        @param turn_silence_ms 换人静音阈值（毫秒）
        @param frame_duration_ms 单帧时长（毫秒）
        @throws ValueError 阈值非正、或换人阈值不大于句末阈值时抛出
        """
        if end_silence_ms <= 0 or turn_silence_ms <= 0 or frame_duration_ms <= 0:
            raise ValueError("静音阈值与帧长都必须为正数")
        if turn_silence_ms <= end_silence_ms:
            raise ValueError(
                f"换人阈值必须大于句末阈值，否则两者同时到达时行为不确定："
                f"turn={turn_silence_ms} end={end_silence_ms}"
            )
        self._end_silence_ms = end_silence_ms
        self._turn_silence_ms = turn_silence_ms
        self._frame_duration_ms = frame_duration_ms
        self._state = SentenceState.IDLE
        self._silence_ms = 0
        self._frames: list[bytes] = []
        self._segment_emitted = False

    def state(self) -> SentenceState:
        """查询当前状态。

        @return 当前状态
        """
        return self._state

    def feed(self, is_speech: bool) -> SentenceEvent:
        """喂入一帧的判定结果。

        @param is_speech 该帧是否有人声
        @return 本次喂入产生的事件
        """
        if is_speech:
            self._silence_ms = 0
            self._state = SentenceState.SPEAKING
            # 新一轮人声重新武装句末事件：上一句已经交付过了。
            self._segment_emitted = False
            return SentenceEvent(EVENT_NONE)

        self._state = SentenceState.SILENCE
        self._silence_ms += self._frame_duration_ms

        if self._silence_ms >= self._turn_silence_ms:
            # 换人：丢弃已收集的音频，之前的半句作废。
            self._frames = []
            self._silence_ms = 0
            self._state = SentenceState.IDLE
            self._segment_emitted = False
            return SentenceEvent(EVENT_TURN_CHANGE)

        if self._silence_ms >= self._end_silence_ms and not self._segment_emitted:
            # 句末：把已收集的音频交出去。事件**只发一次** ——
            # 否则一段静音里的每一帧都会触发一次 ASR，安静环境下会疯狂转写。
            # 但静音计时继续累计，这样后续更长的静音仍能触发换人。
            self._segment_emitted = True
            frames = self._frames
            self._frames = []
            return SentenceEvent(EVENT_SEGMENT_END, frames)

        return SentenceEvent(EVENT_NONE)

    def push_frame(self, frame: bytes) -> None:
        """收集一帧音频。

        @param frame 一帧 PCM 字节
        """
        self._frames.append(frame)
