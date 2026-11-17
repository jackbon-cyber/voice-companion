"""端侧语音识别适配层。

把「端侧 ASR」抽象成一个接口，是为了在模型缺失时仍能跑通全链路：
`faster-whisper` 的模型权重需要按需下载，评审者的机器上未必有；
此时端侧应当**降级**（`NullRecognizer` + 规则意图），而不是崩掉。

因此本模块的实现约定是：**任何实现都不允许在识别失败时抛出异常**，
失败一律表现为「空文本 + 零置信度」，由上层据此拒识。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

# 默认识别置信度阈值。低于该值视为拒识，不上云。
DEFAULT_CONFIDENCE_THRESHOLD = 0.5

# 默认模型规格。base 是速度与精度的平衡点，适合端侧 CPU 实时场景。
DEFAULT_MODEL_SIZE = "base"

# 默认推理设备。端侧 PC 模拟器没有 GPU。
DEFAULT_DEVICE = "cpu"

# 默认计算精度。int8 量化是 CPU 上的常规选择。
DEFAULT_COMPUTE_TYPE = "int8"

# 本地模型目录相对仓库根。与 core/scripts/fetch-models.ps1 的落盘位置一致。
DEFAULT_MODEL_DIR = Path("core/models/asr")


@dataclass(frozen=True)
class RecognitionResult:
    """一次识别的结果。"""

    text: str
    confidence: float
    language: str


class SpeechRecognizer(Protocol):
    """端侧语音识别器契约。"""

    hotwords: list[str]

    def transcribe(self, pcm: bytes) -> RecognitionResult:
        """识别一段 PCM 音频。

        @param pcm PCM 音频字节
        @return 识别结果；失败时返回空文本与零置信度，不抛异常
        """
        ...


class NullRecognizer:
    """永远识别不出东西的识别器。

    用于模型缺失时的降级路径：整条链路照常运行，只是端侧不再识别语音，
    改由规则意图与云端兜底。
    """

    def __init__(self) -> None:
        """构造降级识别器。"""
        self.hotwords: list[str] = []

    def transcribe(self, pcm: bytes) -> RecognitionResult:
        """返回空结果。

        @param pcm PCM 音频字节，不作使用
        @return 空文本、零置信度的识别结果
        """
        return RecognitionResult(text="", confidence=0.0, language="zh")


class FasterWhisperRecognizer:
    """基于 faster-whisper（CTranslate2 后端）的识别器。"""

    def __init__(
        self,
        model_size: str = DEFAULT_MODEL_SIZE,
        device: str = DEFAULT_DEVICE,
        compute_type: str = DEFAULT_COMPUTE_TYPE,
        model_dir: Path | None = None,
    ) -> None:
        """加载识别模型。

        @param model_size 模型规格名；提供 model_dir 时该参数被忽略
        @param device 推理设备
        @param compute_type 计算精度
        @param model_dir 本地模型目录；提供时从该目录加载，不访问网络
        @throws RuntimeError 模型加载失败时抛出，消息里给出可执行的补救指引
        """
        try:
            from faster_whisper import WhisperModel
        except ImportError as error:
            raise RuntimeError(
                "端侧 ASR 需要 faster-whisper：请先执行 "
                "`pip install -r core/requirements.txt`"
            ) from error

        try:
            if model_dir is not None:
                # 本地目录加载：不触网。模型文件由 core/scripts/fetch-models.ps1 备好。
                self._model = WhisperModel(
                    str(model_dir), device=device, compute_type=compute_type
                )
            else:
                self._model = WhisperModel(model_size, device=device, compute_type=compute_type)
        except Exception as error:
            raise RuntimeError(
                f"端侧 ASR 模型 {model_dir or model_size} 加载失败：{error}。"
                "请先执行 `core/scripts/fetch-models.ps1` 下载模型权重。"
            ) from error

        self._hotwords: list[str] = []

    @property
    def hotwords(self) -> list[str]:
        """热词列表。

        @return 当前热词
        """
        return self._hotwords

    @hotwords.setter
    def hotwords(self, words: list[str]) -> None:
        """设置热词。

        热词用于提升人设专有名词与用户称呼的识别率。

        @param words 热词列表
        """
        self._hotwords = list(words)

    def transcribe(self, pcm: bytes) -> RecognitionResult:
        """识别一段 PCM 音频。

        @param pcm PCM 音频字节
        @return 识别结果；识别失败时返回空文本与零置信度，不抛异常
        """
        if not pcm:
            return RecognitionResult(text="", confidence=0.0, language="zh")

        try:
            segments, _ = self._model.transcribe(
                self._to_float32(pcm),
                language="zh",
                hotwords=build_prompt_text(self._hotwords),
            )
            for segment in segments:
                text = (segment.text or "").strip()
                if text:
                    return RecognitionResult(
                        text=text,
                        confidence=self._to_confidence(getattr(segment, "avg_logprob", None)),
                        language="zh",
                    )
        except Exception:
            # 识别失败表现为空结果：上层据此拒识，比把异常抛到主循环安全。
            return RecognitionResult(text="", confidence=0.0, language="zh")

        return RecognitionResult(text="", confidence=0.0, language="zh")

    def _to_confidence(self, avg_logprob: float | None) -> float:
        """把 Whisper 的平均对数概率换算成 [0, 1] 的置信度。

        faster-whisper 给的是 ``avg_logprob``（自然对数刻度，典型值在 -1 到 0 之间），
        它不是概率。直接拿它跟 0.5 比较会得出"几乎总是拒识"的结论，
        因此这里取指数还原为概率。

        @param avg_logprob 平均对数概率，可为 None
        @return 置信度，取值区间 [0, 1]
        """
        if avg_logprob is None:
            return 0.0
        return max(0.0, min(1.0, math.exp(avg_logprob)))

    def _to_wav(self, pcm: bytes) -> bytes:
        """把裸 PCM 包成 WAV。

        @param pcm PCM 音频字节
        @return WAV 文件字节
        """
        import io
        import wave

        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(16000)
            wav_file.writeframes(pcm)
        return buffer.getvalue()

    def _to_float32(self, pcm: bytes):
        """把裸 PCM 转成归一化浮点数组。

        **为什么直接喂数组而不是 WAV 文件**：faster-whisper 收到 numpy 数组时
        会跳过音频解码，而解码那一步依赖 PyAV。本机 PyAV 19 已移除
        ``av.open(..., metadata_errors=...)`` 参数，与 faster-whisper 1.1.1
        不兼容，表现为识别一律失败并返回空文本 —— 而异常被识别器的兜底
        分支吞掉，从外面看只是"识别不准"，排查方向会被带偏。

        我们的输入本来就是 16 kHz 单声道 16-bit PCM，**无需任何解码**：
        直接转成浮点数组既绕开 PyAV，也让端侧路径更短。

        @param pcm PCM 音频字节
        @return 归一化后的 float32 数组
        """
        import numpy as np

        samples = np.frombuffer(pcm, dtype=np.int16)
        return pcm_to_float32(samples)


# 简体偏置提示语。
#
# **为什么必须有它**：Whisper 的中文训练数据里繁体占比很高，
# 不给偏置时"今天天气真不错"会被识别成"今天天氣真不錯"。
# 对陪伴机器人而言这是**功能性缺陷**而非观感问题 ——
# 下游的关键词意图匹配会全部失效（"别说了" 匹配不上 "別說了"）。
MANDARIN_PROMPT = "以下是普通话的句子。"


def build_prompt_text(hotwords: list[str]) -> str:
    """构造识别提示语。

    @param hotwords 热词列表
    @return 提示语文本；无热词时只含普通话偏置
    """
    parts = [MANDARIN_PROMPT]
    meaningful = [word.strip() for word in hotwords if word and word.strip()]
    if meaningful:
        parts.append("、".join(meaningful))
    return " ".join(parts)


def pcm_to_float32(samples):
    """把 16-bit 有符号 PCM 样本归一化到 [-1, 1] 的 float32 数组。

    **除以 32768 而不是 32767**：Whisper 的特征提取器假定输入满幅为 1.0。
    用 32767 会让峰值略大于 1，对短音频的静音段判定有影响。

    @param samples int16 样本数组
    @return 归一化后的 float32 数组
    """
    import numpy as np

    return samples.astype(np.float32) / 32768.0


def create_recognizer(model_dir: Path | None = None) -> SpeechRecognizer:
    """构造识别器：本地模型优先，缺失时降级。

    **优先本地目录而非模型名**：用模型名构造会触发 HuggingFace Hub 联网下载，
    在离��环境里表现为「连接超时」，排查方向会被带到网络问题上。
    本地模型由 `core/scripts/fetch-models.ps1` 备好，目录存在就直接用。

    降级到 {@link NullRecognizer} 而不是抛异常：端侧在缺模型时仍要能跑通全链路。

    @param model_dir 本地模型目录；为 None 时取默认路径
    @return 识别器
    """
    directory = model_dir or DEFAULT_MODEL_DIR
    if directory.is_dir() and (directory / "model.bin").exists():
        try:
            return FasterWhisperRecognizer(model_dir=directory)
        except RuntimeError:
            # 本地模型损坏时同样降级：整条链路不能因为识别器起不来而断掉。
            pass
    return NullRecognizer()


def is_confident(result: RecognitionResult, threshold: float = DEFAULT_CONFIDENCE_THRESHOLD) -> bool:
    """判定识别结果是否可信到可以上云。

    **先判文本非空，再判置信度**：空文本的高置信度是模型噪声而非有效识别，
    例如背景音被识别成了一串标点，置信度可能反而不低。

    @param result 识别结果
    @param threshold 置信度阈值
    @return 可信返回 True
    """
    if not result.text.strip():
        return False
    return result.confidence >= threshold
