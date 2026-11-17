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
from dataclasses import dataclass, field
from pathlib import Path

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

    raw, source_rate = _read_wav_as_pcm(wav_path)
    return resample(raw, source_rate, SAMPLE_RATE)


def _temp_wav_path() -> Path:
    """返回临时 WAV 文件路径。

    :return: 临时文件路径
    """
    import tempfile

    return Path(tempfile.gettempdir()) / "voice_companion_asr_sample.wav"


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


def add_noise(pcm: bytes, snr_db: int) -> bytes:
    """给 PCM 音频叠加高斯噪声。

    :param pcm: 原始 PCM 字节
    :param snr_db: 目标信噪比（dB）
    :return: 加噪后的 PCM 字节
    """
    import array
    import math
    import random

    samples = array.array("h")
    samples.frombytes(pcm)
    if not samples:
        return pcm

    signal_power = sum(float(value) ** 2 for value in samples) / len(samples)
    if signal_power <= 0.0:
        return pcm

    noise_power = signal_power / (10 ** (snr_db / 10.0))
    noise_sigma = math.sqrt(noise_power)

    generator = random.Random(20261116)
    noisy = array.array("h")
    for value in samples:
        noise = generator.gauss(0.0, noise_sigma)
        clipped = max(-32768, min(32767, int(value + noise)))
        noisy.append(clipped)
    return noisy.tobytes()


def evaluate(eval_dir: Path) -> tuple[dict[str, ConditionResult], bool]:
    """执行端侧识别评测。

    :param eval_dir: 评测集目录
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

    for condition, reference in samples:
        if condition not in SNR_BY_CONDITION:
            print(f"未知噪声条件 '{condition}'，跳过", file=sys.stderr)
            continue

        result = results.setdefault(condition, ConditionResult(condition=condition))
        result.sample_count += 1

        try:
            pcm = synthesize(reference)
        except RuntimeError as error:
            print(f"音频合成失败：{error}", file=sys.stderr)
            return results, False

        noisy = add_noise(pcm, SNR_BY_CONDITION[condition])
        recognized = recognizer.transcribe(noisy).text.strip()

        rate = character_error_rate(reference, recognized)
        result._rates.append(rate)
        if recognized == reference:
            result.correct_count += 1
        else:
            result.details.append(f"参考={reference} 识别={recognized} CER={rate:.2f}")

    return results, True


def render_report(results: dict[str, ConditionResult]) -> str:
    """渲染端侧识别评测报告。

    :param results: 各条件结果
    :return: Markdown 文本
    """
    lines = [
        "# 端侧识别（ASR）维度评测报告",
        "",
        "**判定依据：最差噪声条件下的识别准确率**。",
        "准确率对噪声极敏感，只报一个总体数字会把「模型不行」与「环境太吵」混为一谈。",
        "",
        "| 噪声条件 | 信噪比 | 样本数 | 准确率 | 字符错误率 | 判定 |",
        "|---|---|---|---|---|---|",
    ]

    worst: ConditionResult | None = None
    for condition in ("clean", "mild", "noisy"):
        result = results.get(condition)
        if result is None:
            continue
        if worst is None or result.accuracy < worst.accuracy:
            worst = result
        lines.append(
            f"| {condition} | {SNR_BY_CONDITION[condition]} dB | {result.sample_count} "
            f"| {result.accuracy * 100:.1f}% | {result.character_error_rate:.3f} "
            f"| {'—' if result.sample_count < MIN_SAMPLE_SIZE else '样本不足，不参与判定'} |"
        )

    lines.append("")
    if worst is None:
        lines.append("未产出任何样本，端侧识别维度未覆盖。")
        return "\n".join(lines) + "\n"

    passed = worst.accuracy >= MIN_ASR_ACCURACY
    lines.append(
        f"**总体结论：{'通过' if passed else '不通过'}**"
        f"（最差条件 {worst.condition}，准确率 {worst.accuracy * 100:.1f}%，"
        f"阈值 {MIN_ASR_ACCURACY * 100:.0f}%）"
    )
    lines.append("")
    lines.append("> 说明：音频由 TTS 合成，合成音与真人语音存在差距，")
    lines.append("> 因此本报告的准确率**偏乐观**，不应作为真机指标。")

    failures = [detail for result in results.values() for detail in result.details]
    if failures:
        lines.append("")
        lines.append("## 未识别一致的明细")
        lines.append("")
        for detail in failures:
            lines.append(f"- {detail}")

    return "\n".join(lines) + "\n"


def main() -> None:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="端侧识别维度评测")
    parser.add_argument("--eval-dir", default=DEFAULT_EVAL_DIR, help="评测集目录")
    parser.add_argument("--report", default=None, help="Markdown 报告输出路径")
    args = parser.parse_args()

    results, available = evaluate(Path(args.eval_dir))
    if not available:
        raise SystemExit(EXIT_ENV_UNAVAILABLE)

    report = render_report(results)
    if args.report:
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report, encoding="utf-8")

    print(report)

    worst = min(results.values(), key=lambda item: item.accuracy) if results else None
    if worst is None:
        raise SystemExit(EXIT_ENV_UNAVAILABLE)
    if worst.sample_count < MIN_SAMPLE_SIZE:
        raise SystemExit(EXIT_PASSED)
    raise SystemExit(EXIT_PASSED if worst.accuracy >= MIN_ASR_ACCURACY else 1)


if __name__ == "__main__":
    main()
