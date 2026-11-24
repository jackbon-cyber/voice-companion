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
import os
import platform
import time
from collections.abc import Callable
from pathlib import Path

from core.edge.asr.recognizer import RecognitionResult, is_confident
from core.edge.audio.framer import AudioFramer, Frame
from core.edge.audio.negotiation import DEFAULT_FORMAT, AudioFormat
from core.edge.audio.sentence import SentenceEvent, SentenceSegmenter
from core.edge.audio.vad import VoiceActivityDetector
from core.edge.degrade.policy import DegradeLevel, DegradePolicy
from core.edge.dialog.engine import LocalDialogEngine, create_dialog_engine
from core.edge.dialog.factual import FactualGuard
from core.edge.dialog.responder import LocalReply, LocalResponder
from core.edge.intent.detector import IntentDecision, IntentDetector
from core.edge.metrics.collector import MetricsCollector
from core.edge.metrics.reporter import MetricsReporter
from core.edge.session.state_machine import SessionStateMachine
from core.edge.transport.downlink import TextReply, VoiceChunk
from core.edge.transport.uplink import UplinkAuthError, UplinkClient, UplinkError

# 日志器。
LOGGER = logging.getLogger(__name__)

# 默认的云端上行地址。
DEFAULT_CLOUD_URL = "ws://127.0.0.1:8080/voice/uplink"

# 默认会话标识。
DEFAULT_SESSION_ID = "session-local-1"

# 模拟源的默认间隔（毫秒）。真实场景是 20 毫秒一帧，这里放慢便于观察。
DEFAULT_SOURCE_INTERVAL_MS = 200


def _elapsed_micros(started_at: float) -> int:
    """计算从给定时刻起经过的微秒数。

    用单调时钟而非墙钟：墙钟会被 NTP 校时与系统时间调整影响，
    测出的耗时会突然出现负数或巨大的跳变。

    返回微秒而非毫秒：VAD 与意图判定只花几十微秒，按毫秒取整会全部变成 0。

    @param started_at 起始时刻（``time.perf_counter`` 的返回值）
    @return 经过的微秒数
    """
    return int((time.perf_counter() - started_at) * 1_000_000)


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

    #: 等待云端回复的**最长**秒数。
    #:
    #: 为什么需要"等回复"而不是"睡固定时长"：云端回复的耗时随链路而变 ——
    #: 有记忆召回时要走嵌入与向量检索，可能好几秒。
    #: 睡固定 0.3 秒会让**所有**较慢的回复被系统性地漏掉，
    #: 表现为"云端明明回了，端侧却当没收到"。
    #: 指标采集同样受影响：漏掉回复就没有往返耗时样本，
    #: 而缺失的指标在报告里会被标成"未覆盖"，白白丢掉真实可测的量。
    REPLY_WAIT_TIMEOUT_SECONDS = 30.0

    #: 收到回复后再多等一会儿，让同一轮的其余下行消息（如语音片段）到达。
    POST_REPLY_SETTLE_SECONDS = 0.3

    #: 本地应答的来源标识。与云端回复区分开，不得混为一谈。
    LOCAL_REPLY_SOURCE = "LOCAL"

    def __init__(
        self,
        session_id: str,
        cloud_url: str,
        audio_format: AudioFormat = DEFAULT_FORMAT,
        phrases: list[str] | None = None,
        dialog_engine: LocalDialogEngine | None = None,
        token: str | None = None,
        owner_key: str | None = None,
    ) -> None:
        """构造模拟端。

        @param session_id 会话标识
        @param cloud_url 云端上行地址
        @param audio_format 音频格式
        @param phrases 模拟源依次"说"出的语句
        @param dialog_engine 本地对话引擎；为 None 时用话术库
        @param token 接入凭据；为 None 时不带凭据
        @param owner_key 会话归属的用户标识。云端据此绑定记忆作用域 ——
            没有它，云端写的记忆全部落进同一个作用域，跨用户隔离无从谈起。
        """
        self._session_id = session_id
        self._cloud_url = cloud_url
        self._format = audio_format
        self._phrases = phrases or ["把音量调到五十", "今天发生了好多事情啊"]
        self._client = UplinkClient(
            session_id=session_id,
            base_url=cloud_url,
            token=token,
            owner_key=owner_key,
        )
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
        self._responder = LocalResponder(
            engine=dialog_engine or create_dialog_engine(None),
            factual_guard=self._factual_guard,
        )
        self._clock_ms = 0
        #: 本地应答记录。供测试断言与"本轮是否产生了本地回复"的查询。
        self._local_replies: list[LocalReply] = []
        #: 最近一次上行请求发出的时刻（单调时钟）。为 None 表示当前没有在等下行。
        self._request_sent_at: float | None = None
        #: 下行消息观察者。端到端验证用它读取引用来源。
        self._downlink_observer: Callable[[object], None] | None = None
        #: 本轮是否已收到下行回复。等待方据此判断"可以继续了"。
        self._reply_arrived = False

    @property
    def metrics(self) -> MetricsCollector:
        """分段耗时采集器。

        @return 采集器
        """
        return self._metrics

    @property
    def local_replies(self) -> list[LocalReply]:
        """已产生的本地应答。

        @return 本地应答列表
        """
        return list(self._local_replies)

    @property
    def is_offline(self) -> bool:
        """当前是否处于离线档位。

        @return 离线档位时为 True
        """
        return self._degrade.current() in (
            DegradeLevel.OFFLINE,
            DegradeLevel.MINIMAL,
        )

    def set_downlink_observer(self, observer: Callable[[object], None] | None) -> None:
        """设置下行消息观察者。

        @param observer 观察者；为 None 时取消观察
        """
        self._downlink_observer = observer

    def set_scripted_phrases(self, phrases: list[str]) -> None:
        """替换识别脚本。

        端到端验证需要**逐轮控制**用户说什么 ——
        同一个模拟端实例里，第一轮说"我妈妈叫李芳"，
        第二轮说"我妈妈叫什么"，两轮必须分别可控。

        @param phrases 依次"说"出的语句
        """
        self._phrases = list(phrases)
        self._source = SimulatedAudioSource(self._phrases, self._format)
        self._recognizer = ScriptedRecognizer(self._phrases)


    async def run(self, rounds: int = 2) -> None:
        """跑若干轮对话。

        云端连不上时**不抛异常**：端侧必须能独立完成陪伴应答。
        连不上就降级到离线档，继续跑本地链路。

        @param rounds 轮数
        """
        try:
            await self._client.connect(self._format)
            await self._client.send_session_begin(self._format)
        except UplinkAuthError as error:
            # 鉴权失败是**配置问题**，不是网络问题。
            # 静默降级到本地陪伴会把"凭据错了"伪装成"网络断了"，
            # 让人往错误的方向排查。这里明确报出来并中止。
            LOGGER.error("上行鉴权失败：%s", error)
            raise
        except UplinkError as error:
            # 连接失败 = 对端明确不可达，直接落到离线档。
            self._degrade.record_connection_failure()
            # **措辞上要区分"预期降级"与"意外不可达"**：
            # 端到端脚本里会**故意断连**来验证离线降级，
            # 这条 WARN 在那种场景下是**预期输出**。
            # 但它同时也是"云端真的没起来"的唯一信号 ——
            # 两者混在一起时，看输出的人无法判断这次降级是设计内的还是故障。
            # 因此这里只报事实（连不上 + 降到哪档），由调用方决定怎么解读：
            # 端到端脚本会自己加上"这是预期行为"的说明。
            LOGGER.warning(
                "云端不可达（%s），降级为 %s，转入本地陪伴模式",
                error,
                self._degrade.current().value,
            )
            await self._run_offline_rounds(rounds)
            return

        LOGGER.info("已连接云端并开始会话：%s", self._cloud_url)

        # 下行读取放到后台任务：与上行并行，否则上行会阻塞在下行等待上。
        receiver = asyncio.create_task(self._receive_downlink())

        try:
            for round_index in range(rounds):
                await self._run_round(round_index)
                await self._wait_for_reply(round_index)
        finally:
            receiver.cancel()
            await self._client.send_session_end("simulator_finished")
            await self._client.close()

    async def _run_offline_rounds(self, rounds: int) -> None:
        """在离线档位下跑若干轮本地陪伴。

        离线时没有音频上行，也没有云端回复，但用户说话仍要得到回应 ——
        否则设备在离线场景下等同于坏掉。

        @param rounds 轮数
        """
        for round_index in range(rounds):
            phrase = self._phrases[round_index % len(self._phrases)] if self._phrases else ""
            if not phrase:
                continue
            self._clock_ms += 20
            self._state_machine.on_user_speech_start(self._clock_ms)
            self._state_machine.on_recognized(phrase)
            self._state_machine.on_local_processing_started(self._clock_ms)

            guard_result = self._responder.check_factual(phrase)
            if guard_result.should_go_to_cloud:
                # 离线时查不了事实，只能明说自己离线，不能编造。
                reply = self._responder.respond_factual(phrase, offline=True)
            else:
                reply = self._responder.respond(phrase, offline=True)

            self._local_replies.append(reply)
            LOGGER.info(
                "第 %d 轮（离线，本地产生）：识别=%r 应答=%r（情感=%s）",
                round_index + 1,
                phrase,
                reply.text,
                reply.emotion,
            )
            self._state_machine.on_playback_finished(self._clock_ms)


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
        # 观察者先于业务处理拿到消息：端到端验证需要在状态机变更之前
        # 看到原始消息内容（含引用来源）。
        if self._downlink_observer is not None:
            try:
                self._downlink_observer(message)
            except Exception as error:  # noqa: BLE001 - 观察者不应影响主流程
                LOGGER.warning("下行观察者异常，已忽略：%s", error)

        if isinstance(message, TextReply):
            LOGGER.info("收到云端回复：%r（情感=%s）", message.text, message.emotion)
            # 通知等待方：本轮的回复已经到了。
            self._reply_arrived = True
            # 文本回复也是用户感知的"开始响应"时刻。
            # 首包延迟若只在语音片段上统计，云端只发文本时就永远没有样本 ——
            # 而指标缺失会被报告标成"未覆盖"，白白丢掉一个真实可测的量。
            self._record_first_packet()
            self._record_round_trip()
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
            if latency is not None:
                self._metrics.record_first_packet(latency)
            if message.is_last:
                self._record_round_trip()
                self._state_machine.on_playback_finished(self._clock_ms)
            # 语音链路的最后一片也算"本轮有回复"——
            # 云端下发语音而不是文本时，等待方同样需要被唤醒。
            self._reply_arrived = True

    async def _drain_downlink(self) -> None:
        """等待一小段时间，把已到达的下行消息处理掉。

        @param 无
        """
        await asyncio.sleep(self.DOWNLINK_DRAIN_SECONDS)

    async def _wait_for_reply(self, round_index: int) -> None:
        """等待本轮的下行回复到达。

        **为什么不能睡固定时长**：云端回复的耗时随链路而变 ——
        走记忆召回时要经过嵌入与向量检索，可能好几秒。
        睡固定 0.3 秒会让**所有**较慢的回复被系统性地漏掉，
        表现为"云端明明回了，端侧却当没收到"；
        指标采集同样受影响 —— 漏掉回复就没有往返耗时样本，
        而缺失的指标在报告里会被标成"未覆盖"，白白丢掉真实可测的量。

        因此这里等到**真的收到一条回复**为止，只在超时后才放弃。
        超时放弃而不是无限等待：云端挂住时不能让整个流程卡死。

        @param round_index 轮次序号
        """
        if self._request_sent_at is None:
            # 本轮没有上行（例如意图在端侧本地处理），只需短暂排空下行。
            await self._drain_downlink()
            return

        deadline = time.perf_counter() + self.REPLY_WAIT_TIMEOUT_SECONDS
        while time.perf_counter() < deadline:
            if self._reply_arrived:
                self._reply_arrived = False
                # 收到回复后再等一小会儿，让同一轮的其余下行消息到达。
                await asyncio.sleep(self.POST_REPLY_SETTLE_SECONDS)
                return
            await asyncio.sleep(0.02)

        LOGGER.warning(
            "第 %d 轮：等待云端回复超时（%.0f 秒），按未收到处理",
            round_index + 1,
            self.REPLY_WAIT_TIMEOUT_SECONDS,
        )
        self._request_sent_at = None

    async def _run_round(self, round_index: int) -> None:
        """跑一轮。

        @param round_index 轮次序号
        """
        frames = await self._source.frames()
        speech_started = False

        for frame in frames:
            vad_started = time.perf_counter()
            is_speech = self._vad.is_speech_frame(frame.payload)
            self._metrics.record_vad_micros(_elapsed_micros(vad_started))

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

    def _record_round_trip(self) -> None:
        """记录一次上云往返耗时。

        往返耗时从**上行发出**算到**下行到达**，不含端侧本地处理 ——
        本地处理另有 VAD/识别/意图三个指标单独统计。
        两者混在一起会让人分不清"慢在本地"还是"慢在网络"。
        """
        if self._request_sent_at is None:
            return
        self._metrics.record_round_trip(_elapsed_micros(self._request_sent_at) / 1000)
        self._request_sent_at = None

    def _record_first_packet(self) -> None:
        """记录一次首包延迟。

        首包延迟与往返耗时的区别：**首包**是用户感知的"开始响应"时刻，
        **往返**是整条回复到达的时刻。第一阶段云端只发一条完整文本回复，
        两者数值接近；接入流式 TTS 后首包会显著小于往返。
        """
        if self._request_sent_at is None:
            return
        self._metrics.record_first_packet(_elapsed_micros(self._request_sent_at) / 1000)

    async def _handle_segment(self, round_index: int, frames: list[bytes]) -> None:
        """处理一个语句段。

        @param round_index 轮次序号
        @param frames 该段的音频字节
        """
        asr_started = time.perf_counter()
        result: RecognitionResult = self._recognizer.transcribe(b"".join(frames))
        self._metrics.record_asr_micros(_elapsed_micros(asr_started))

        if not is_confident(result):
            LOGGER.info("第 %d 轮：识别不可信（%r），拒识不上云", round_index + 1, result.text)
            return

        self._state_machine.on_recognized(result.text)
        self._state_machine.on_local_processing_started(self._clock_ms)

        # 事实性请求先过守卫：端侧不得编造具体事实，只能引导上云求证。
        guard_started = time.perf_counter()
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
                ),
                result.text,
            )
            return

        intent_started = time.perf_counter()
        decision = self._intent.detect(result.text, result.confidence)
        self._metrics.record_intent_micros(_elapsed_micros(intent_started))
        LOGGER.info(
            "第 %d 轮：识别=%r 意图=%s 本地处理=%s",
            round_index + 1,
            result.text,
            decision.intent,
            decision.handled_locally,
        )

        if not decision.handled_locally:
            self._state_machine.on_cloud_wait_started(self._clock_ms)
            if await self._send_intent_report(decision, result.text):
                # 上行成功，等云端回复。
                return
            # 上行失败且已降级到离线：不能让用户干等一个不会来的云端回复，
            # 转为本地陪伴应答。
            self._respond_locally(round_index, result.text)
            self._state_machine.on_playback_finished(self._clock_ms)
            return

        # 本地已处理的意图**不上行**：端侧规则表已经执行完，再上行只会让云端
        # 多生成一条回复，而这条回复对应的是"我已经做完了"，
        # 用户会看到机器人答非所问地接话。
        LOGGER.info("意图在端侧本地执行，不上行")
        self._respond_locally(round_index, result.text)
        self._state_machine.on_playback_finished(self._clock_ms)

    def _respond_locally(self, round_index: int, text: str) -> LocalReply:
        """生成一次本地陪伴应答并记录。

        事实性请求走引导话术而不是陪伴话术：陪伴话术是情绪回应，
        用它回答"我上次血压多少"会让用户以为机器人回避了问题。

        @param round_index 轮次序号
        @param text 用户说的文本
        @return 本地应答
        """
        offline = self.is_offline
        guard_result = self._responder.check_factual(text)
        if guard_result.should_go_to_cloud:
            reply = self._responder.respond_factual(text, offline=offline)
        else:
            reply = self._responder.respond(text, offline=offline)
        self._local_replies.append(reply)
        LOGGER.info(
            "第 %d 轮：本地产生应答=%r（情感=%s 离线=%s 来源=%s）",
            round_index + 1,
            reply.text,
            reply.emotion,
            reply.offline,
            reply.source,
        )
        return reply

    async def _send_intent_report(self, decision: IntentDecision, text: str = "") -> bool:
        """上行一条意图报告。

        @param decision 意图判定结果
        @param text 识别出的用户原话。云端据此写入长期记忆并做召回 ——
            没有原话，云端只拿到意图标识，无法记住用户说过的话。
        @return 上行是否成功
        """
        try:
            await self._client.send_intent(decision, text)
        except UplinkError as error:
            LOGGER.warning("意图上行失败：%s", error)
            self._degrade.record_uplink_failure()
            return False
        self._degrade.record_uplink_success()
        # 记录发出时刻：往返耗时从此刻算到下行到达。
        self._request_sent_at = time.perf_counter()
        return True

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
    parser.add_argument(
        "--token",
        default=os.environ.get("VOICE_UPLINK_TOKEN"),
        help="接入凭据。默认取环境变量 VOICE_UPLINK_TOKEN。",
    )
    parser.add_argument(
        "--owner",
        default=os.environ.get("VOICE_OWNER_KEY"),
        help="会话归属的用户标识。默认取环境变量 VOICE_OWNER_KEY。",
    )
    parser.add_argument(
        "--metrics-out",
        default=None,
        help="把分段耗时报告导出到指定路径（Markdown）。",
    )
    parser.add_argument(
        "--metrics-json-out",
        default=None,
        help="把分段耗时报告导出到指定路径（JSON）。",
    )
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
        token=args.token,
        owner_key=args.owner,
    )
    try:
        await simulator.run(rounds=args.rounds)
    except UplinkAuthError as error:
        # 鉴权失败退出码用 2，与"网络不可达降级继续跑"（退出码 0）区分开。
        LOGGER.error("上行鉴权失败：%s", error)
        raise SystemExit(2)
    except UplinkError as error:
        LOGGER.error("上行链路失败：%s", error)
        return
    LOGGER.info("模拟结束。降级档位：%s", simulator.degrade_level().value)
    if simulator.local_replies:
        LOGGER.info(
            "本轮共产生 %d 条本地应答（来源均为 LOCAL，未伪装为云端回复）",
            len(simulator.local_replies),
        )
    _export_metrics(simulator, args)


def _export_metrics(simulator: EdgeSimulator, args: argparse.Namespace) -> None:
    """导出分段耗时报告。

    @param simulator 模拟端
    @param args 命令行参数
    """
    if not args.metrics_out and not args.metrics_json_out:
        return

    reporter = MetricsReporter(simulator.metrics)
    environment = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "rounds": str(args.rounds),
        "degradeLevel": simulator.degrade_level().value,
    }
    if args.metrics_out:
        path = Path(args.metrics_out)
        reporter.export_markdown(path, environment)
        LOGGER.info("分段耗时报告已导出：%s", path)
    if args.metrics_json_out:
        path = Path(args.metrics_json_out)
        reporter.export_json(path, environment)
        LOGGER.info("分段耗时报告已导出：%s", path)


if __name__ == "__main__":
    asyncio.run(main())
