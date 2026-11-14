"""端侧模拟端主循环。

把端侧各模块串成一条可运行的链路：

```
麦克风（模拟）→ 帧组装 → VAD → 断句 → ASR → 意图判定 → 上行 → 下行 → 播报
```

第一阶段不接真实麦克风与扬声器：音频输入来自一个**文本驱动的模拟源**
（读入音频文件或生成测试音），输出打到控制台。这样在没有声卡、没有模型、
没有网络的机器上也能跑通整条链路 —— 这是"零硬件可跑通"硬指标的落地方式。

用法：

```powershell
cd core
F:\\tools\\python313\\python.exe -m core.edge.simulator --url ws://127.0.0.1:8080/voice/uplink
```
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Callable
from pathlib import Path

from core.edge.asr.recognizer import RecognitionResult, is_confident
from core.edge.audio.framer import AudioFramer, Frame
from core.edge.audio.negotiation import DEFAULT_FORMAT, AudioFormat
from core.edge.audio.sentence import SentenceEvent, SentenceSegmenter
from core.edge.audio.vad import VoiceActivityDetector
from core.edge.degrade.policy import DegradeLevel, DegradePolicy
from core.edge.dialog.factual import FactualGuard
from core.edge.intent.detector import IntentDecision, IntentDetector
from core.edge.metrics.collector import MetricsCollector
from core.edge.session.state_machine import SessionStateMachine
from core.edge.transport.downlink import TextReply, VoiceChunk
from core.edge.transport.uplink import UplinkClient, UplinkError

# 日志器。
LOGGER = logging.getLogger(__name__)

# 默认的云端上行地址。
DEFAULT_CLOUD_URL = "ws://127.0.0.1:8080/voice/uplink"

# 默认会话标识。
DEFAULT_SESSION_ID = "session-local-1"

# 模拟源的默认间隔（毫秒）。真实场景是 20 毫秒一帧，这里放慢便于观察。
DEFAULT_SOURCE_INTERVAL_MS = 200


class SimulatedAudioSource:
    """文本驱动的模拟音频源。

    它不产生真实音频，而是把"用户说的话"转成连续的静音与有声片段，
    用来驱动 VAD 与断句状态机。这样整条链路可以在无声卡的机器上跑通。
    """

    def __init__(self, phrases: list[str], format: AudioFormat) -> None:
        """构造模拟音频源。

        @param phrases 依次"说"出的语句
        @param format 音频格式
        """
        self._phrases = phrases
        self._format = format

    async def frames(self) -> list[Frame]:
        """产出一轮：有声段 + 静音段。

        @return 帧列表
        """
        framer = AudioFramer(
            sample_rate=self._format.sample_rate,
            frame_duration_ms=self._format.frame_duration_ms,
        )
        frame_bytes = framer.frame_bytes

        emitted: list[Frame] = []
        # 有声段：一整帧能量足够高，VAD 会判有人声。
        for _ in range(5):
            emitted.extend(framer.push(b"\x11" * frame_bytes))
        # 静音段：足够长，让断句状态机走到句末阈值。
        for _ in range(40):
            emitted.extend(framer.push(b"\x00" * frame_bytes))

        # 末尾补齐帧（若有）。
        emitted.extend(framer.flush())
        return emitted


class ScriptedRecognizer:
    """按脚本返回识别结果的识别器。

    真实端侧用 {@code FasterWhisperRecognizer}；没有模型时用
    {@code NullRecognizer}，识别结果恒为空，**意图判定这条链路就永远走不到**，
    模拟端也就演示不出端云交互的全貌。

    本类把"这一轮用户说了什么"直接作为识别结果返回，让模拟端能演示完整的
    识别 → 意图 → 上行链路。它只属于模拟端，不进入生产路径。
    """

    def __init__(self, phrases: list[str]) -> None:
        """构造脚本识别器。

        @param phrases 依次返回的识别文本
        """
        self._phrases = phrases
        self._index = 0
        self.hotwords: list[str] = []

    def transcribe(self, pcm: bytes) -> RecognitionResult:
        """返回下一条脚本文本。

        @param pcm PCM 音频字节，不作使用
        @return 识别结果
        """
        if not self._phrases:
            return RecognitionResult(text="", confidence=0.0, language="zh")
        text = self._phrases[self._index % len(self._phrases)]
        self._index += 1
        return RecognitionResult(text=text, confidence=0.9, language="zh")


class EdgeSimulator:
    """端侧模拟端。"""

    #: 每轮结束后等待下行消息到达的秒数。
    DOWNLINK_DRAIN_SECONDS = 0.3

    def __init__(
        self,
        session_id: str,
        cloud_url: str,
        audio_format: AudioFormat = DEFAULT_FORMAT,
        phrases: list[str] | None = None,
    ) -> None:
        """构造模拟端。

        @param session_id 会话标识
        @param cloud_url 云端上行地址
        @param audio_format 音频格式
        @param phrases 模拟源依次"说"出的语句
        """
        self._session_id = session_id
        self._cloud_url = cloud_url
        self._format = audio_format
        self._phrases = phrases or ["把音量调到五十", "今天发生了好多事情啊"]
        self._client = UplinkClient(session_id=session_id, base_url=cloud_url)
        self._vad = VoiceActivityDetector()
        self._segmenter = SentenceSegmenter(
            end_silence_ms=600,
            turn_silence_ms=2000,
            frame_duration_ms=audio_format.frame_duration_ms,
        )
        self._recognizer = ScriptedRecognizer(self._phrases)
        self._intent = IntentDetector()
        self._degrade = DegradePolicy()
        self._metrics = MetricsCollector()
        self._source = SimulatedAudioSource(self._phrases, audio_format)
        self._state_machine = SessionStateMachine()
        self._factual_guard = FactualGuard()
        self._clock_ms = 0

    async def run(self, rounds: int = 2) -> None:
        """跑若干轮对话。

        @param rounds 轮数
        """
        await self._client.connect(self._format)
        await self._client.send_session_begin(self._format)
        LOGGER.info("已连接云端并开始会话：%s", self._cloud_url)

        # 下行读取放到后台任务：与上行并行，否则上行会阻塞在下行等待上。
        receiver = asyncio.create_task(self._receive_downlink())

        try:
            for round_index in range(rounds):
                await self._run_round(round_index)
                await self._drain_downlink()
        finally:
            receiver.cancel()
            await self._client.send_session_end("simulator_finished")
            await self._client.close()

    async def _receive_downlink(self) -> None:
        """后台接收下行消息。"""
        try:
            while True:
                message = await self._client.receive_downlink(self._clock_ms)
                if message is None:
                    # 连接已关闭或读取失败。
                    return
                self._on_downlink(message)
        except asyncio.CancelledError:
            raise
        except Exception as error:  # noqa: BLE001 - 后台任务不能因异常静默退出
            LOGGER.warning("下行接收异常，已停止：%s", error)

    def _on_downlink(self, message: object) -> None:
        """处理一条下行消息。

        @param message 下行消息
        """
        if isinstance(message, TextReply):
            LOGGER.info("收到云端回复：%r（情感=%s）", message.text, message.emotion)
            self._state_machine.on_playback_finished(self._clock_ms)
        elif isinstance(message, VoiceChunk):
            latency = self._client.downlink.first_packet_latency_ms(0)
            LOGGER.info(
                "收到语音片段：序号=%d 首包=%s 末包=%s 首包延迟=%sms",
                message.sequence,
                message.is_first,
                message.is_last,
                latency,
            )
            if message.is_last:
                self._state_machine.on_playback_finished(self._clock_ms)

    async def _drain_downlink(self) -> None:
        """等待一小段时间，把已到达的下行消息处理掉。

        @param 无
        """
        await asyncio.sleep(self.DOWNLINK_DRAIN_SECONDS)

    async def _run_round(self, round_index: int) -> None:
        """跑一轮。

        @param round_index 轮次序号
        """
        frames = await self._source.frames()
        speech_started = False

        for frame in frames:
            is_speech = self._vad.is_speech_frame(frame.payload)
            await self._client.send_frames([frame])
            # 收集该帧音频，断句到句末时一并交给识别。
            self._segmenter.push_frame(frame.payload)

            if is_speech and not speech_started:
                speech_started = True
                self._clock_ms += 20
                barge_in = self._state_machine.on_user_speech_start(self._clock_ms)
                if barge_in is not None:
                    LOGGER.info("检测到打断，丢弃 %d 字节待播音频", barge_in.discarded_audio_bytes)

            event = self._segmenter.feed(is_speech)
            if event.kind == "segment_end":
                await self._handle_segment(round_index, event.frames)
            elif event.kind == "turn_change":
                LOGGER.info("检测到换人，本轮输入作废")

    async def _handle_segment(self, round_index: int, frames: list[bytes]) -> None:
        """处理一个语句段。

        @param round_index 轮次序号
        @param frames 该段的音频字节
        """
        result: RecognitionResult = self._recognizer.transcribe(b"".join(frames))

        if not is_confident(result):
            LOGGER.info("第 %d 轮：识别不可信（%r），拒识不上云", round_index + 1, result.text)
            return

        self._state_machine.on_recognized(result.text)
        self._state_machine.on_local_processing_started(self._clock_ms)

        # 事实性请求先过守卫：端侧不得编造具体事实，只能引导上云求证。
        guard_result = self._factual_guard.check(result.text)
        if guard_result.should_go_to_cloud:
            LOGGER.info(
                "第 %d 轮：识别=%r 属事实性请求（%s），引导上云求证，不在端侧作答",
                round_index + 1,
                result.text,
                guard_result.category.value if guard_result.category else "未知",
            )
            self._state_machine.on_cloud_wait_started(self._clock_ms)
            await self._send_intent_report(
                IntentDecision(
                    intent="unknown",
                    confidence=result.confidence,
                    handled_locally=False,
                )
            )
            return

        decision = self._intent.detect(result.text, result.confidence)
        LOGGER.info(
            "第 %d 轮：识别=%r 意图=%s 本地处理=%s",
            round_index + 1,
            result.text,
            decision.intent,
            decision.handled_locally,
        )

        if not decision.handled_locally:
            self._state_machine.on_cloud_wait_started(self._clock_ms)
            await self._send_intent_report(decision)
            return

        # 本地已处理的意图**不上行**：端侧规则表已经执行完，再上行只会让云端
        # 多生成一条回复，而这条回复对应的是"我已经做完了"，
        # 用户会看到机器人答非所问地接话。
        LOGGER.info("意图在端侧本地执行，不上行")
        self._state_machine.on_playback_finished(self._clock_ms)

    async def _send_intent_report(self, decision: IntentDecision) -> None:
        """上行一条意图报告。

        @param decision 意图判定结果
        """
        try:
            await self._client.send_intent(decision)
        except UplinkError as error:
            LOGGER.warning("意图上行失败：%s", error)
            self._degrade.record_uplink_failure()

    def degrade_level(self) -> DegradeLevel:
        """查询当前降级档位。

        @return 降级档位
        """
        return self._degrade.current()


def build_parser() -> argparse.ArgumentParser:
    """构造命令行解析器。

    @return 解析器
    """
    parser = argparse.ArgumentParser(description="语音陪伴机器人端侧模拟端")
    parser.add_argument("--url", default=DEFAULT_CLOUD_URL, help="云端上行地址")
    parser.add_argument("--session", default=DEFAULT_SESSION_ID, help="会话标识")
    parser.add_argument("--rounds", type=int, default=2, help="对话轮数")
    parser.add_argument("--phrase", action="append", default=None, help="模拟说出的语句，可重复")
    return parser


async def main() -> None:
    """模拟端入口。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = build_parser().parse_args()

    simulator = EdgeSimulator(
        session_id=args.session,
        cloud_url=args.url,
        phrases=args.phrase,
    )
    try:
        await simulator.run(rounds=args.rounds)
    except UplinkError as error:
        LOGGER.error("上行链路失败：%s", error)
        return
    LOGGER.info("模拟结束。降级档位：%s", simulator.degrade_level().value)


if __name__ == "__main__":
    asyncio.run(main())
