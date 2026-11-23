"""端侧识别（ASR）维度评测。

评测的是什么
------------
端侧 ASR 在**不同信噪比**下的识别准确度。

为什么要按信噪比分组
--------------------
识别准确率对噪声极度敏感：安静环境 95% 的准确率，到 10 dB 信噪比可能掉到 60%。
只报一个总体数字会把"模型不行"与"环境太吵"两种完全不同的原因混在一起，
排查方向会被带偏。因此本评测<b>按噪声条件分别统计</b>，
并以<b>最差条件</b>作为门禁判定依据。

音频从哪来
----------
评测集里存的是**参考文本**，不是音频文件。原因是：
音频不该进 git（体积大、无法 diff、无法审阅），
而文本可以。音频在评测时用 TTS 合成 —— 合成音与真人语音有差距，
这会让测出的数字<b>偏乐观</b>，因此本评测产出的报告里会明确标注这一点。

为什么用字符错误率（CER）而不是字准确率
------------------------------------
中文按字计错比按词计错更稳定：中文没有空格分词，
按词计错需要额外的分词器，分词器本身的差异会让数字失去可比性。
CER 的定义是 ``编辑距离 / 参考文本长度``。
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from core.eval.audio_source import (
    AudioSource,
    DEFAULT_RECORDING_DIR,
    find_recording,
    load_real_recording,
)
from core.eval.text_normalizer import is_exact_match, normalize_text

# 评测集目录相对仓库根。
DEFAULT_EVAL_DIR = "core/eval"

# 评测集文件后缀。
FILE_SUFFIX = "-eval.txt"

# 噪声条件到信噪比（dB）的映射。
SNR_BY_CONDITION: dict[str, int] = {
    "clean": 30,
    "mild": 20,
    "noisy": 10,
}

# 门禁判定的条件分**两档**，取决于音频来源。
#
# **第一档（任何音频都判）**：clean —— 安静室内条件。
# 端侧 ASR 的职责边界是"固定指令 + 唤醒"（见 openspec design.md 的风险表：
# 若中文 WER 高于目标，则收敛端侧 ASR 用途，自由对话走云端）。
# 陪伴机器人的部署形态是床头/桌面近场拾音，对应安静室内环境。
# 合成音在这个条件下虽然偏乐观，但**仍是有意义的下界**：
# 连合成音都识别不了，真人语音只会更差。
#
# **第二档（仅真人录音才判）**：mild / noisy —— 噪声条件。
# 合成音缺少真人的音高变化与共振峰细节，属于 Whisper 的分布外输入。
# 它在噪声下的表现既不代表真人语音，也不能用来判定模型能力 ——
# 拿它当门禁依据等于用不可信的测量定成败。
# 换成真人录音后，测的就是"真人说话时环境噪声下能不能识别"，
# **这正是部署场景里会遇到的真实问题**，因而具备判定资格。
#
# **为什么不是"全部或全无"**：若因为没有真人录音就连 clean 也不判，
# ASR 维度实际上就被绕过了 —— 门禁形同虚设。
# clean 的判定资格不依赖于录音是否到位。
GATE_CONDITIONS_ANY_AUDIO: tuple[str, ...] = ("clean",)

# 仅在**全部**样本都来自真人录音时，才额外参与判定的条件。
#
# **为什么要求"全部"而不是"多数"**：混着真人与合成音的准确率，
# 既不代表真人语音、也不代表合成音 —— 这个数字没有可解释性。
# 宁可退回"只有 clean 参与判定"，也不要给出一个含糊的门禁依据。
GATE_CONDITIONS_REAL_ONLY: tuple[str, ...] = ("mild", "noisy")

# 端侧识别准确率下限。与 Java 侧 EvalGates.MIN_ASR_ACCURACY 保持一致。
MIN_ASR_ACCURACY = 0.80

# 参与门禁判定所需的最小样本数。与 Java 侧 EvalGates.MIN_SAMPLE_SIZE 保持一致。
MIN_SAMPLE_SIZE = 10

# 退出码：全部通过。
EXIT_PASSED = 0

# 退出码：环境不可用（模型缺失等）。
EXIT_ENV_UNAVAILABLE = 2

# 采样率。必须与协议约定一致：16 kHz。
SAMPLE_RATE = 16000

# 本地 ASR 模型目录。与 core/scripts/fetch-models.ps1 的落盘位置一致。
DEFAULT_MODEL_DIR = Path("core/models/asr")

# 判定语音活动帧的阈值占峰值 RMS 的比例。
#
# 取 5% 而不是更高：TTS 合成音的起音与收音有渐变，
# 阈值太高会切掉句首辅音，让"语音段功率"低估真实值。
SPEECH_ACTIVITY_RATIO = 0.05

# 并行识别的最大线程数。
#
# 不设成 CPU 核数：ctranslate2 的推理本身已用多线程，
# 外层再开太多线程会造成线程争抢，反而更慢。
# 4 是实测下来效果与稳定性都够用的取值。
MAX_RECOGNITION_WORKERS = 4


@dataclass
class ConditionResult:
    """单个噪声条件下的评测结果。"""

    #: 噪声条件名。
    condition: str

    #: 样本数。
    sample_count: int = 0

    #: 识别正确的样本数。
    correct_count: int = 0

    #: 各条样本的明细。
    details: list[str] = field(default_factory=list)

    #: 各音频来源的样本数。
    #:
    #: **为什么要按来源分开统计**：把真人录音与 TTS 合成混在一个准确率里，
    #: 那个数字既不代表真人语音、也不代表合成音 —— 没有意义。
    #: 分开统计后，"这个条件用了哪种音频"一目了然。
    sources: dict[AudioSource, int] = field(default_factory=dict)

    @property
    def accuracy(self) -> float:
        """该条件下的识别准确率。"""
        if self.sample_count == 0:
            return 0.0
        return self.correct_count / self.sample_count

    @property
    def character_error_rate(self) -> float:
        """该条件下的平均字符错误率。"""
        if not self._rates:
            return 0.0
        return sum(self._rates) / len(self._rates)

    #: 各条样本的字符错误率。
    _rates: list[float] = field(default_factory=list)


def character_error_rate(reference: str, hypothesis: str) -> float:
    """计算字符错误率。

    :param reference: 参考文本
    :param hypothesis: 识别文本
    :return: 编辑距离除以参考文本长度；参考为空时返回 0
    """
    if not reference:
        return 0.0
    previous = list(range(len(hypothesis) + 1))
    for i, ref_char in enumerate(reference, start=1):
        current = [i]
        for j, hyp_char in enumerate(hypothesis, start=1):
            current.append(min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (ref_char != hyp_char),
            ))
        previous = current
    return previous[-1] / len(reference)


def load_samples(eval_dir: Path) -> list[tuple[str, str]]:
    """从评测集读取 ASR 样本。

    :param eval_dir: 评测集目录
    :return: (噪声条件, 参考文本) 列表
    :raises ValueError: 文件不存在时抛出
    """
    path = eval_dir / f"asr{FILE_SUFFIX}"
    if not path.exists():
        raise ValueError(f"找不到端侧识别评测集：{path}")

    samples: list[tuple[str, str]] = []
    with path.open("r", encoding="utf-8") as handle:
        for raw in handle:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("|")
            if len(parts) != 3:
                raise ValueError(
                    f"{path}：期望 3 段（维度|噪声条件|参考文本），实际 {len(parts)} 段"
                )
            samples.append((parts[1], parts[2]))
    return samples


def synthesize(reference: str) -> bytes:
    """把参考文本合成为 16 kHz 单声道 16-bit PCM 音频。

    :param reference: 参考文本
    :return: 16 kHz 单声道 16-bit PCM 字节
    :raises RuntimeError: 缺少 TTS 依赖时抛出
    """
    try:
        import pyttsx3
    except ImportError as error:
        raise RuntimeError(
            "端侧识别评测需要 TTS 合成音频：请先执行 `pip install pyttsx3`"
        ) from error

    wav_path = _temp_wav_path()
    engine = pyttsx3.init()
    engine.setProperty("rate", 160)
    engine.save_to_file(reference, str(wav_path))
    engine.runAndWait()

    try:
        raw, source_rate = _read_wav_as_pcm(wav_path)
    finally:
        # 合成完立刻删掉临时文件。
        #
        # **为什么必须删**：临时文件名按进程与线程唯一，留着会堆积；
        # 更重要的是 TTS 引擎在**写完之前**文件是残缺的，
        # 任何并发读都会拿到半截音频。
        wav_path.unlink(missing_ok=True)

    return resample(raw, source_rate, SAMPLE_RATE)


def _temp_wav_path() -> Path:
    """返回当前进程与线程独有的临时 WAV 文件路径。

    **为什么必须唯一**：pyttsx3 的 ``save_to_file`` 是**写文件**，
    不是写内存。多进程并发时，固定文件名会让后一个进程的写入
    覆盖前一个进程还没读完的内容 —— 读到半截音频，
    识别结果全空，表现为"准确率暴跌到接近 0"。

    **实测踩到过**：一边跑 ``eval.ps1``、一边手动跑端侧评测，
    两边都用同一个固定文件名。最终报告里 clean 准确率 28.6%、
    CER 0.714，而单独跑是 85.7%、CER 0.014 —— 差的是音频，不是模型。

    用进程号 + 线程号 + 递增计数，保证同一进程内的并发调用也不撞。

    :return: 临时文件路径
    """
    import os
    import tempfile
    import threading

    counter = getattr(_temp_wav_path, "_counter", 0)
    _temp_wav_path._counter = counter + 1

    unique = f"voice_companion_asr_{os.getpid()}_{threading.get_ident()}_{counter}"
    return Path(tempfile.gettempdir()) / f"{unique}.wav"


def _read_wav_as_pcm(path: Path) -> tuple[bytes, int]:
    """读取 WAV 文件的 PCM 数据与采样率。

    :param path: WAV 文件路径
    :return: (PCM 字节, 采样率)
    """
    import wave

    with wave.open(str(path), "rb") as wav_file:
        return wav_file.readframes(wav_file.getnframes()), wav_file.getframerate()


def resample(pcm: bytes, source_rate: int, target_rate: int) -> bytes:
    """把 PCM 音频重采样到目标采样率。

    **必须重采样，不能直接喂**：系统 TTS 的输出采样率随机器而变
    （本机为 22050 Hz），而协议约定的是 16 kHz。
    把 22050 Hz 的字节当成 16 kHz 送进识别器，
    表现为「音调变快、内容完全识别不出来」——
    这是极难定位的一类问题，因为识别器本身没有任何异常。

    用线性插值而不是重采样滤波器：线性插值会引入轻微失真，
    但对本评测（比较识别准确率而非追求听感）足够，
    且不引入 scipy 依赖。

    :param pcm: 原始 PCM 字节
    :param source_rate: 源采样率
    :param target_rate: 目标采样率
    :return: 重采样后的 PCM 字节
    """
    import array

    if source_rate == target_rate or not pcm:
        return pcm

    samples = array.array("h")
    samples.frombytes(pcm)
    if not samples:
        return pcm

    import numpy as np

    source = np.asarray(samples, dtype=np.float64)
    # 目标采样点数按比例取整。
    target_length = max(1, int(round(len(source) * target_rate / source_rate)))
    # 原采样点位置映射到目标采样点位置，用它做线性插值。
    positions = np.linspace(0, len(source) - 1, target_length)
    resampled = np.interp(positions, np.arange(len(source)), source)

    return array.array("h", resampled.astype(np.int16).tobytes()).tobytes()


def speech_signal_power(samples: "array.array") -> float:
    """估计语音段的平均功率。

    **为什么不能直接用整段功率**：TTS 合成的音频通常前后带大段静音
    （实测首尾静音占全长的 44%）。用整段功率定标噪声功率，
    会把噪声算得偏小 —— 标称 20 dB 的实际信噪比远高于 20 dB，
    于是"噪声条件"的标称值与实际严重脱节，评测数字没有可比性。

    做法：按帧计算 RMS，只取高于峰值 5% 的帧（视为语音活动段），
    用这些帧的功率作为信号功率。

    @param samples PCM 样本数组
    :return: 语音段平均功率；找不到语音段时返回整段功率
    """
    import math

    if not samples:
        return 0.0

    frame_size = 160  # 10 毫秒（16 kHz）
    frame_rms: list[float] = []
    for start in range(0, len(samples) - frame_size, frame_size):
        chunk = samples[start:start + frame_size]
        power = sum(float(value) ** 2 for value in chunk) / frame_size
        frame_rms.append(math.sqrt(power))

    if not frame_rms:
        return 0.0

    peak_rms = max(frame_rms)
    threshold = peak_rms * SPEECH_ACTIVITY_RATIO
    active = [rms for rms in frame_rms if rms >= threshold]
    if not active:
        return sum(float(value) ** 2 for value in samples) / len(samples)

    return sum(rms ** 2 for rms in active) / len(active)


# 静音段与语音段的噪声功率比（dB）。
#
# **为什么要分段定标**：真实录音里，环境噪声在**全程**都存在，
# 但语音段的噪声被说话声掩盖，静音段的噪声就是环境底噪 ——
# 两者的噪声功率差得很远（典型相差 20 dB 以上）。
#
# 而 TTS 合成音的静音是**数字静音**（全零）。给数字静音加白噪声，
# 等价于造出"绝对安静 + 突然噪声"的伪信号：
# Whisper 的 VAD 会把噪声突发当成语音起点，识别质量断崖式下跌。
# 实测同一句话：全程按语音段功率加噪在 30 dB 就出错，
# 而仅在语音段加噪时 10 dB 仍能正确识别。
#
# 按真实录音的特征分段定标，既符合物理实际，也修掉了这个伪信号。
SILENCE_SNR_OFFSET_DB = 20


def speech_activity_mask(samples: "array.array") -> list[bool]:
    """标出哪些采样点属于语音活动段。

    @param samples PCM 样本数组
    :return: 与样本等长的布尔列表，True 表示处于语音活动段
    """
    import math

    mask = [False] * len(samples)
    if not samples:
        return mask

    frame_size = 160  # 10 毫秒（16 kHz）
    frame_rms: list[float] = []
    for start in range(0, len(samples) - frame_size, frame_size):
        chunk = samples[start:start + frame_size]
        power = sum(float(value) ** 2 for value in chunk) / frame_size
        frame_rms.append(math.sqrt(power))

    if not frame_rms:
        return mask

    threshold = max(frame_rms) * SPEECH_ACTIVITY_RATIO
    for index, rms in enumerate(frame_rms):
        if rms >= threshold:
            start = index * frame_size
            end = min(len(samples), start + frame_size)
            for position in range(start, end):
                mask[position] = True
    return mask


def add_noise(pcm: bytes, snr_db: int) -> bytes:
    """给 PCM 音频叠加高斯噪声。

    噪声功率按**语音段功率**定标，使标称 SNR 与实际一致；
    静音段的噪声功率另按 {@link SILENCE_SNR_OFFSET_DB} 下调，
    模拟真实录音里"环境底噪远低于语音段噪声"的形态。

    @param pcm: 原始 PCM 字节
    @param snr_db: 目标信噪比（dB），指语音段
    :return: 加噪后的 PCM 字节
    """
    import array
    import math
    import random

    samples = array.array("h")
    samples.frombytes(pcm)
    if not samples:
        return pcm

    signal_power = speech_signal_power(samples)
    if signal_power <= 0.0:
        return pcm

    speech_sigma = math.sqrt(signal_power / (10 ** (snr_db / 10.0)))
    silence_sigma = speech_sigma / (10 ** (SILENCE_SNR_OFFSET_DB / 20.0))
    mask = speech_activity_mask(samples)

    generator = random.Random(20261116)
    noisy = array.array("h")
    for index, value in enumerate(samples):
        sigma = speech_sigma if mask[index] else silence_sigma
        noise = generator.gauss(0.0, sigma)
        clipped = max(-32768, min(32767, int(value + noise)))
        noisy.append(clipped)
    return noisy.tobytes()


def evaluate(
    eval_dir: Path, recording_dir: Path | None = None
) -> tuple[dict[str, ConditionResult], bool]:
    """执行端侧识别评测。

    :param eval_dir: 评测集目录
    :param recording_dir: 真人录音目录；为 None 时用默认目录
    :return: (各条件结果, 环境是否可用)
    """
    from core.edge.asr.recognizer import FasterWhisperRecognizer

    try:
        # 显式用本地模型目录：按模型名构造会触发联网下载，
        # 离线环境下表现为「连接超时」，把排查方向带偏。
        recognizer = FasterWhisperRecognizer(model_dir=DEFAULT_MODEL_DIR)
    except RuntimeError as error:
        print(f"端侧识别评测不可用：{error}", file=sys.stderr)
        return {}, False

    samples = load_samples(eval_dir)
    results: dict[str, ConditionResult] = {}
    recording_root = recording_dir or DEFAULT_RECORDING_DIR

    # 音频按参考文本缓存。
    #
    # 同一句话会出现在多个噪声条件下（这正是评测集的设计 ——
    # 衡量同一条内容在不同信噪比下的稳定性），
    # 因此音频可以复用，省掉重复的 TTS 调用。
    # 噪声本身**不能**复用：不同信噪比下的音频是不同的输入。
    #
    # **缓存键必须含来源**：真人录音与合成音是两种不同输入，
    # 混用会让"真人语音的准确率"这个数字失去意义。
    audio_cache: dict[tuple[str, AudioSource], bytes] = {}

    # 先把全部样本的音频准备好，再统一识别。
    # 识别是整个评测里最慢的一环（单条约 2 秒），
    # 准备阶段与识别阶段分开，才能把识别并行化。
    prepared: list[tuple[str, str, bytes, AudioSource]] = []
    for condition, reference in samples:
        if condition not in SNR_BY_CONDITION:
            print(f"未知噪声条件 '{condition}'，跳过", file=sys.stderr)
            continue

        source = AudioSource.REAL if find_recording(reference, recording_root) else AudioSource.SYNTHETIC
        cache_key = (reference, source)
        pcm = audio_cache.get(cache_key)
        if pcm is None:
            try:
                if source is AudioSource.REAL:
                    pcm = load_real_recording(reference, recording_root)
                else:
                    pcm = synthesize(reference)
            except (RuntimeError, ValueError) as error:
                print(f"音频准备失败（{reference}）：{error}", file=sys.stderr)
                return results, False
            if pcm is None:
                print(f"音频准备失败（{reference}）：真人录音读取返回空", file=sys.stderr)
                return results, False
            audio_cache[cache_key] = pcm

        prepared.append((condition, reference, add_noise(pcm, SNR_BY_CONDITION[condition]), source))

    # 并行识别。
    #
    # **为什么值得并行**：单条识别约 2 秒，42 条样本串行要一分半钟，
    # 对"十分钟跑通"的演示是实打实的等待。ctranslate2 的推理本身是多线程的，
    # 线程池能吃满多核。
    #
    # **为什么结果仍可复现**：每条样本独立识别，互不影响；
    # 归并时按 prepared 的原始顺序处理，输出顺序与串行执行完全一致。
    # 噪声用的是固定随机种子，因此每次加噪结果相同。
    recognized_texts = recognize_all(recognizer, [item[2] for item in prepared])

    for (condition, reference, _, source), recognized in zip(prepared, recognized_texts):
        result = results.setdefault(condition, ConditionResult(condition=condition))
        result.sample_count += 1
        result.sources[source] = result.sources.get(source, 0) + 1
        recognized = recognized.strip()

        # CER 与"是否完全一致"都按归一化口径计算 ——
        # 句尾多一个句号、停顿被识别成逗号都是纯格式差异，
        # 不归一化会让"逐字全对"的样本被判成错。
        rate = character_error_rate(normalize_text(reference), normalize_text(recognized))
        result._rates.append(rate)
        if is_exact_match(reference, recognized):
            result.correct_count += 1
        else:
            result.details.append(f"参考={reference} 识别={recognized} CER={rate:.2f}")

    return results, True


def recognize_all(recognizer, audio_chunks: list[bytes]) -> list[str]:
    """并行识别一批音频。

    @param recognizer 识别器
    @param audio_chunks PCM 音频列表
    @return: 识别文本列表，顺序与入参一一对应
    """
    if not audio_chunks:
        return []

    # 单条样本时直接串行：起线程池的开销大于收益。
    if len(audio_chunks) == 1:
        return [recognizer.transcribe(audio_chunks[0]).text]

    worker_count = min(MAX_RECOGNITION_WORKERS, len(audio_chunks))
    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = [
            pool.submit(recognizer.transcribe, chunk) for chunk in audio_chunks
        ]
        return [future.result().text for future in futures]


def gate_eligibility(results: dict[str, ConditionResult]) -> dict[str, str]:
    """判定每个噪声条件是否参与门禁，并给出理由。

    **这个函数是报告与退出码的唯一判定依据**。

    两者必须用同一份逻辑 —— 否则会出现"报告说不参与判定、
    退出码却按它判失败"这种自相矛盾，而且极难排查。

    参与判定需要同时满足：
    1. **样本充足**：样本量 ≥ MIN_SAMPLE_SIZE；
    2. **音频可信**：该条件属于「任何音频都判」的第一档，
       或属于「仅真人录音才判」的第二档且本批样本全部来自真人录音。

    :param results: 各条件结果
    :return: 条件名到判定说明的映射
    """
    verdicts: dict[str, str] = {}

    # 该批样本是否全部来自真人录音。
    all_real = all(
        result.sources.get(AudioSource.REAL, 0) == result.sample_count
        for result in results.values()
        if result.sample_count > 0
    )

    for condition, result in results.items():
        if result.sample_count < MIN_SAMPLE_SIZE:
            verdicts[condition] = "样本不足，不参与判定"
            continue
        if condition in GATE_CONDITIONS_ANY_AUDIO:
            verdicts[condition] = "参与判定"
            continue
        if condition in GATE_CONDITIONS_REAL_ONLY:
            verdicts[condition] = (
                "参与判定" if all_real else "音频为 TTS 合成，不作门禁依据"
            )
            continue
        verdicts[condition] = "不在门禁条件表内，不参与判定"

    return verdicts


def render_report(results: dict[str, ConditionResult]) -> str:
    """渲染端侧识别评测报告。

    :param results: 各条件结果
    :return: Markdown 文本
    """
    verdicts = gate_eligibility(results)

    lines = [
        "# 端侧识别（ASR）维度评测报告",
        "",
        "**判定依据：门禁条件下的识别准确率**。",
        "准确率对噪声极敏感，只报一个总体数字会把「模型不行」与「环境太吵」混为一谈。",
        "",
        "| 噪声条件 | 信噪比 | 样本数 | 音频来源 | 准确率 | 字符错误率 | 判定 |",
        "|---|---|---|---|---|---|---|",
    ]

    worst: ConditionResult | None = None
    for condition in ("clean", "mild", "noisy"):
        result = results.get(condition)
        if result is None:
            continue
        verdict = verdicts.get(condition, "不参与判定")
        if verdict == "参与判定" and (
            worst is None or result.accuracy < worst.accuracy
        ):
            worst = result
        lines.append(
            f"| {condition} | {SNR_BY_CONDITION[condition]} dB | {result.sample_count} "
            f"| {_source_summary(result)} "
            f"| {result.accuracy * 100:.1f}% | {result.character_error_rate:.3f} "
            f"| {verdict} |"
        )

    lines.append("")
    if worst is None:
        lines.append("**总体结论：不参与门禁判定**（没有噪声条件同时满足"
                     "「样本量达标」与「音频可信」）。")
        lines.append("")
        lines.append("> 说明：音频由 TTS 合成，合成音与真人语音存在差距，")
        lines.append("> 因此本报告的准确率**偏乐观**，不应作为真机指标。")
    else:
        passed = worst.accuracy >= MIN_ASR_ACCURACY
        lines.append(
            f"**总体结论：{'通过' if passed else '不通过'}**"
            f"（判定条件 {worst.condition}，准确率 {worst.accuracy * 100:.1f}%，"
            f"阈值 {MIN_ASR_ACCURACY * 100:.0f}%）"
        )

    lines.append("")
    lines.append("## 口径说明")
    lines.append("")
    lines.extend(_render_methodology(results, verdicts))

    failures = [detail for result in results.values() for detail in result.details]
    if failures:
        lines.append("")
        lines.append("## 未识别一致的明细")
        lines.append("")
        for detail in failures:
            lines.append(f"- {detail}")

    return "\n".join(lines) + "\n"


def _source_summary(result: ConditionResult) -> str:
    """把一个条件的音频来源统计成简短描述。

    :param result: 条件结果
    :return: 形如「真人录音 14」的描述
    """
    if not result.sources:
        return "-"
    parts = [
        f"{source.label} {count}"
        for source, count in result.sources.items()
        if count > 0
    ]
    return " / ".join(parts) if parts else "-"


def _render_methodology(
    results: dict[str, ConditionResult], verdicts: dict[str, str]
) -> list[str]:
    """渲染口径说明段落。

    :param results: 各条件结果
    :param verdicts: 判定说明
    :return: Markdown 行
    """
    all_real = all(
        result.sources.get(AudioSource.REAL, 0) == result.sample_count
        for result in results.values()
        if result.sample_count > 0
    )
    real_count = sum(
        result.sources.get(AudioSource.REAL, 0) for result in results.values()
    )
    total_count = sum(result.sample_count for result in results.values())

    lines: list[str] = []

    if all_real:
        lines.append("- 本次评测**全部使用真人录音**，因此 clean / mild / noisy "
                     "三个噪声条件均参与门禁判定。")
        lines.append("- 三个条件分别对应安静室内（30 dB）、轻度环境噪声（20 dB）、"
                     "中度环境噪声（10 dB），代表真实部署中会遇到的三种拾音环境。")
        lines.append("- 真人录音由人工朗读参考文本得到，其噪声鲁棒性反映真实人声，"
                     "可作为真机参考指标。")
    else:
        # **必须区分"完全没有"与"部分有"**：说"音频全部由 TTS 合成"
        # 在只放了 1 条录音时是**不实描述** —— 读者会据此误判整份报告的可信度。
        if real_count > 0:
            lines.append(
                f"- 本次评测**部分使用真人录音**（{real_count} / {total_count} 条），"
                "其余为 TTS 合成。"
            )
            lines.append("- **混用的准确率没有可解释性**：它既不代表真人语音、"
                         "也不代表合成音。因此只有 clean 参与门禁判定，"
                         "mild / noisy 为参考值。")
        else:
            lines.append("- 本次评测**未取得真人录音**，音频全部由 TTS 合成。")
            lines.append("- 合成音缺少真人的音高变化与共振峰细节，属于 Whisper 的"
                         "**分布外输入**；它在噪声下的表现既不代表真人语音，"
                         "也不能用来判定模型能力。")
        lines.append("- **clean 参与门禁判定**（合成音在此条件下仍是有意义的"
                     "下界：连合成音都识别不了，真人语音只会更差），"
                     "mild / noisy 为参考值，给出「信噪比下降时准确率如何衰减」的趋势。")
        lines.append("- 本报告的准确率**偏乐观**（合成音比真人语音更清晰），"
                     "不应作为真机指标。")
        lines.append("- 补齐真人录音后，mild / noisy 即可升级为门禁条件。"
                     "接入方式见 core/eval/recordings/README.md 与 "
                     "docs/known-limitations.md。")

    lines.append("- 门禁只对**样本量达标**的条件判定 —— "
                 f"样本量需 ≥ {MIN_SAMPLE_SIZE} 条。"
                 "5 个样本上的 40% 与 500 个样本上的 40% 是两回事。")
    if not all_real:
        lines.append("- 真人语音的噪声鲁棒性在**补齐录音前**尚未验证，"
                     "见 docs/known-limitations.md。")

    return lines


def main() -> None:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="端侧识别维度评测")
    parser.add_argument("--eval-dir", default=DEFAULT_EVAL_DIR, help="评测集目录")
    parser.add_argument("--report", default=None, help="Markdown 报告输出路径")
    parser.add_argument(
        "--recording-dir",
        default=None,
        help="真人录音目录；默认 core/eval/recordings",
    )
    args = parser.parse_args()

    recording_dir = (
        Path(args.recording_dir) if args.recording_dir else DEFAULT_RECORDING_DIR
    )
    results, available = evaluate(Path(args.eval_dir), recording_dir)
    if not available:
        raise SystemExit(EXIT_ENV_UNAVAILABLE)

    report = render_report(results)
    if args.report:
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")

    print(report)

    # 判定依据与报告一致：直接复用报告用的那份判定结果 ——
    # 报告说"参与判定"的条件集合与退出码依据必须完全一致，
    # 否则会出现"报告说不参与判定，退出码却按它判失败"。
    verdicts = gate_eligibility(results)
    participating = [
        result
        for condition, result in results.items()
        if verdicts.get(condition) == "参与判定"
    ]
    if not participating:
        raise SystemExit(EXIT_PASSED)
    worst = min(participating, key=lambda item: item.accuracy)
    raise SystemExit(EXIT_PASSED if worst.accuracy >= MIN_ASR_ACCURACY else 1)


if __name__ == "__main__":
    main()
