"""端侧会话状态机。

机器人说话时用户插话（barge-in），必须立刻闭嘴。状态机负责让"打断"
成为一次**显式状态转移**，而不是散落在各处的布尔标志。

状态流转：

```
IDLE ──用户开口──> LISTENING ──端侧处理──> THINKING ──等云端──> WAITING_CLOUD
                      ▲                                          │
                      │                                    云端下行 │
                      │                                          ▼
                   打断清理                                   SPEAKING
                                                                │
                        IDLE <────────播完 / 超时────────────────┘
```

设计要点：

- **打断只丢"还没播出去"的音频，不丢"已经识别出的文本"。**
  用户打断说"等等"，机器人应该把已识别的那句话接着说完或道歉，
  而不是当作没发生过 —— 这是 3.4 里"已识别文本被保留"的要求。
- **超时回到 IDLE**：云端不回、或识别器卡住，状态机不能卡在某个状态。
  卡在 ``WAITING_CLOUD`` 意味着麦克风再也不听了 —— 用户说什么都没反应。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# 打断响应延迟上限（毫秒）。用户插话后超过这个时间还没闭嘴，就是体验故障。
DEFAULT_INTERRUPT_LATENCY_MS = 300

# 状态机各状态的超时（毫秒）。超时后回到 IDLE。
DEFAULT_STATE_TIMEOUT_MS = 10_000


class SessionState(Enum):
    """端侧会话状态。"""

    #: 空闲，等待用户开口。
    IDLE = "IDLE"
    #: 正在接收用户语音。
    LISTENING = "LISTENING"
    #: 端侧处理中（识别、意图判定）。
    THINKING = "THINKING"
    #: 等待云端下行。
    WAITING_CLOUD = "WAITING_CLOUD"
    #: 正在播放机器人语音。
    SPEAKING = "SPEAKING"
    #: 已被用户打断，正在清理播放缓冲。
    INTERRUPTED = "INTERRUPTED"


@dataclass(frozen=True)
class StateTransition:
    """一次状态转移。"""

    #: 转移前状态。
    previous: SessionState
    #: 转移后状态。
    current: SessionState
    #: 触发原因。
    reason: str
    #: 距上次状态变化的时长（毫秒）。
    elapsed_ms: int


@dataclass
class BargeInEvent:
    """一次打断事件。

    ``retained_text`` 是打断前**已经识别出来**的文本。打断只丢未播出的音频，
    已识别的文本保留 —— 否则用户说"等等"会连同前面那句一起被丢掉。
    """

    #: 打断发生时的状态。
    state: SessionState
    #: 打断响应延迟（毫秒），从开始播放到检测到有人声。
    latency_ms: int
    #: 打断前已识别的文本。
    retained_text: str = ""
    #: 被丢弃的待播音频字节数。
    discarded_audio_bytes: int = 0
    #: 附带说明（如延迟超限）。
    notes: list[str] = field(default_factory=list)


class SessionStateMachine:
    """端侧会话状态机。"""

    def __init__(
        self,
        interrupt_latency_ms: int = DEFAULT_INTERRUPT_LATENCY_MS,
        state_timeout_ms: int = DEFAULT_STATE_TIMEOUT_MS,
    ) -> None:
        """构造状态机。

        @param interrupt_latency_ms 打断响应延迟上限（毫秒）
        @param state_timeout_ms 状态超时（毫秒）
        @throws ValueError 参数非正时抛出
        """
        if interrupt_latency_ms <= 0 or state_timeout_ms <= 0:
            raise ValueError("打断延迟上限与状态超时都必须为正数")
        self._interrupt_latency_ms = interrupt_latency_ms
        self._state_timeout_ms = state_timeout_ms
        self._state = SessionState.IDLE
        self._entered_at_ms = 0
        self._pending_audio_bytes = 0
        self._recognized_text = ""
        self._last_transition: StateTransition | None = None

    def state(self) -> SessionState:
        """查询当前状态。

        @return 当前状态
        """
        return self._state

    def recognized_text(self) -> str:
        """查询已识别文本。

        @return 已识别文本
        """
        return self._recognized_text

    def last_transition(self) -> StateTransition | None:
        """查询最近一次状态转移。

        @return 最近一次转移；尚未发生转移时为 None
        """
        return self._last_transition

    def on_user_speech_start(self, now_ms: int) -> BargeInEvent | None:
        """处理用户开口。

        在机器人说话时，这就是一次打断。

        @param now_ms 当前时间戳（毫秒）
        @return 打断事件；不是打断时为 None
        """
        if self._state is not SessionState.SPEAKING:
            self._transition(SessionState.LISTENING, "user_speech_start", now_ms)
            return None

        latency_ms = now_ms - self._entered_at_ms
        discarded = self._pending_audio_bytes
        notes: list[str] = []
        if latency_ms > self._interrupt_latency_ms:
            notes.append(f"打断响应超出上限：{latency_ms}ms > {self._interrupt_latency_ms}ms")
        event = BargeInEvent(
            state=self._state,
            latency_ms=latency_ms,
            retained_text=self._recognized_text,
            discarded_audio_bytes=discarded,
            notes=notes,
        )
        # 打断后清空待播音频与已识别文本 —— 用户改了主意。
        self._pending_audio_bytes = 0
        self._recognized_text = ""
        self._transition(SessionState.INTERRUPTED, "barge_in", now_ms)
        return event

    def on_recognized(self, text: str) -> None:
        """记录识别出的文本。

        @param text 识别文本
        """
        self._recognized_text = text

    def on_playback_started(self, now_ms: int) -> None:
        """机器人开始播放。

        @param now_ms 当前时间戳（毫秒）
        """
        self._transition(SessionState.SPEAKING, "playback_started", now_ms)

    def on_playback_queued(self, audio_bytes: int) -> None:
        """登记待播音频。

        @param audio_bytes 待播音频字节数
        """
        self._pending_audio_bytes += audio_bytes

    def on_playback_finished(self, now_ms: int) -> None:
        """机器人播完。

        @param now_ms 当前时间戳（毫秒）
        """
        self._pending_audio_bytes = 0
        self._transition(SessionState.IDLE, "playback_finished", now_ms)

    def on_local_processing_started(self, now_ms: int) -> None:
        """端侧开始处理。

        @param now_ms 当前时间戳（毫秒）
        """
        self._transition(SessionState.THINKING, "local_processing", now_ms)

    def on_cloud_wait_started(self, now_ms: int) -> None:
        """开始等待云端。

        @param now_ms 当前时间戳（毫秒）
        """
        self._transition(SessionState.WAITING_CLOUD, "cloud_wait", now_ms)

    def on_timeout(self, now_ms: int) -> StateTransition | None:
        """检查并处理状态超时。

        卡在 ``WAITING_CLOUD`` 意味着麦克风不再听 —— 这是最危险的超时。
        超时后强制回到 IDLE，保证用户随时可以重新开口。

        @param now_ms 当前时间戳（毫秒）
        @return 超时引发的转移；未超时时为 None
        """
        if self._state is SessionState.IDLE:
            return None
        if now_ms - self._entered_at_ms < self._state_timeout_ms:
            return None
        return self._transition(SessionState.IDLE, "state_timeout", now_ms)

    def _transition(self, target: SessionState, reason: str, now_ms: int) -> StateTransition:
        """执行状态转移。

        @param target 目标状态
        @param reason 转移原因
        @param now_ms 当前时间戳（毫秒）
        @return 本次转移
        """
        transition = StateTransition(
            previous=self._state,
            current=target,
            reason=reason,
            elapsed_ms=now_ms - self._entered_at_ms,
        )
        self._state = target
        self._entered_at_ms = now_ms
        self._last_transition = transition
        return transition
