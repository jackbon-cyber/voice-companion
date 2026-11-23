"""端侧识别评测的音频来源。

**为什么需要这个模块**

端侧识别评测原本只有一种音频来源：**TTS 合成**。这带来两个问题：

1. **合成音不是人声**。它缺少真人的音高变化、共振峰细节、语速波动，
   属于 Whisper 的分布外输入。实测 clean 条件准确率 85.7%，
   但这个数字**不代表真人语音**。
2. **不能参与噪声条件判定**。mild / noisy 条件测的是"噪声下能不能识别"，
   而合成音在噪声下的表现既不代表真人、也不能用来判定模型能力。

引入真人录音后，评测就能给出**可信**的噪声鲁棒性数字。

**三种来源的定位**

| 来源 | 用途 | 门禁资格 |
|---|---|---|
| `real` 真人录音 | 代表真实用户的声音 | clean/mild/noisy **全部可判** |
| `synthetic` TTS 合成 | 无录音时的回退 | 仅 clean 可判 |
| `missing` 两者都无 | 该条样本不可用 | 不参与判定 |

**关键约束：来源必须逐条标注，不能混在一起算**

如果把真人录音与合成音**混在一个准确率里**，那个数字没有意义 ——
它既不是"真人语音的表现"，也不是"合成音的表现"。
所以每条样本都必须带上自己的来源，报告按来源分组统计。

**真人录音放在哪**

录音**不进 git**（体积大、无法 diff、无法审阅）。
约定放在 ``core/eval/recordings/`` 下，由 ``.gitignore`` 排除。
文件名规则：``<参考文本的稳定标识>.wav``，用哈希而非原文 ——
中文文件名在跨平台与 shell 转义上都容易出问题。
"""

from __future__ import annotations

import hashlib
import wave
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# 真人录音目录（相对仓库根）。
#
# **为什么不放在 data/ 下**：data/ 是运行期产物目录（会被整个忽略），
# 录音是评测**输入**，需要被单独管理 —— 放在 core/eval/ 下
# 可以对它写一条精确的 .gitignore 规则，而不是跟着 data/ 一起被忽略掉。
DEFAULT_RECORDING_DIR = Path("core/eval/recordings")

# 录音文件支持的扩展名。
#
# wav 是首选（无损、无需解码依赖）；mp3/flac 是常见的人工录制格式，
# 允许存在但读取需要额外依赖，缺依赖时明确报错而不是静默跳过。
SUPPORTED_EXTENSIONS: tuple[str, ...] = (".wav",)


class AudioSource(Enum):
    """单条评测样本的音频来源。"""

    #: 真人录音。
    REAL = "real"

    #: TTS 合成。
    SYNTHETIC = "synthetic"

    #: 两者都不可用。
    MISSING = "missing"

    @property
    def label(self) -> str:
        """报告里显示的中文名。"""
        return {
            AudioSource.REAL: "真人录音",
            AudioSource.SYNTHETIC: "TTS 合成",
            AudioSource.MISSING: "不可用",
        }[self]


@dataclass(frozen=True)
class AudioSample:
    """一条带来源标注的音频样本。

    @param pcm 16 kHz 单声道 16-bit PCM 字节
    @param source 音频来源
    @param reference 参考文本
    """

    #: PCM 数据。
    pcm: bytes

    #: 音频来源。
    source: AudioSource

    #: 参考文本。
    reference: str

    @property
    def is_real(self) -> bool:
        """是否来自真人录音。"""
        return self.source is AudioSource.REAL


def recording_name_for(reference: str) -> str:
    """由参考文本推导录音文件名（不含扩展名）。

    **为什么用哈希而不是原文做文件名**：中文文件名在 Windows 的
    GBK 代码页、POSIX 的 shell 转义、以及 Git 的路径处理上都容易出问题。
    哈希是纯 ASCII，且天然规避了"两个不同的文本清洗后同名"的情况。

    @param reference 参考文本
    @return 文件名主干
    """
    digest = hashlib.sha256(reference.encode("utf-8")).hexdigest()[:16]
    return f"recording_{digest}"


def find_recording(reference: str, recording_dir: Path) -> Path | None:
    """查找某条参考文本对应的真人录音。

    @param reference 参考文本
    @param recording_dir 录音目录
    @return 录音路径；不存在时返回 None
    """
    stem = recording_name_for(reference)
    for extension in SUPPORTED_EXTENSIONS:
        candidate = recording_dir / f"{stem}{extension}"
        if candidate.is_file():
            return candidate
    return None


def read_wav_as_pcm(path: Path) -> tuple[bytes, int]:
    """读取 WAV 文件的 PCM 数据与采样率。

    @param path WAV 文件路径
    @return (PCM 字节, 采样率)
    @raises ValueError 文件不是合法 WAV 时抛出
    """
    try:
        with wave.open(str(path), "rb") as wav_file:
            if wav_file.getsampwidth() != 2:
                raise ValueError(
                    f"{path}：只支持 16-bit 采样，当前是 {wav_file.getsampwidth() * 8}-bit"
                )
            if wav_file.getnchannels() != 1:
                raise ValueError(
                    f"{path}：只支持单声道，当前是 {wav_file.getnchannels()} 声道"
                )
            return wav_file.readframes(wav_file.getnframes()), wav_file.getframerate()
    except wave.Error as error:
        raise ValueError(f"{path}：不是合法的 WAV 文件（{error}）") from error


def load_real_recording(reference: str, recording_dir: Path) -> bytes | None:
    """读取某条参考文本的真人录音并重采样到 16 kHz。

    @param reference 参考文本
    @param recording_dir 录音目录
    @return 16 kHz 单声道 16-bit PCM 字节；没有录音时返回 None
    @raises ValueError 录音格式不合法时抛出
    """
    from core.eval.edge_eval import resample

    path = find_recording(reference, recording_dir)
    if path is None:
        return None

    raw, source_rate = read_wav_as_pcm(path)
    return resample(raw, source_rate, 16000)


def describe_recording_coverage(
    references: list[str], recording_dir: Path
) -> dict[AudioSource, int]:
    """统计一组参考文本的录音覆盖情况。

    @param references 参考文本列表
    @param recording_dir 录音目录
    @return 来源到条数的映射
    """
    counts = {source: 0 for source in AudioSource}
    for reference in references:
        if find_recording(reference, recording_dir) is not None:
            counts[AudioSource.REAL] += 1
        else:
            counts[AudioSource.SYNTHETIC] += 1
    return counts


def load_eval_references(eval_dir: Path) -> list[str]:
    """从端侧识别评测集里读出全部参考文本（去重且保持顺序）。

    :param eval_dir: 评测集目录
    :return: 参考文本列表
    @raises ValueError 评测集不存在或格式不合法时抛出
    """
    path = eval_dir / "asr-eval.txt"
    if not path.exists():
        raise ValueError(f"找不到端侧识别评测集：{path}")

    references: list[str] = []
    seen: set[str] = set()
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
            reference = parts[2]
            if reference not in seen:
                seen.add(reference)
                references.append(reference)
    return references


def _display_width(text: str) -> int:
    """计算文本在等宽终端里的显示宽度。

    **为什么要自己算**：中文与全角标点是双宽字符，
    按字符数算宽度会让对齐参差不齐。

    :param text 文本
    :return: 显示宽度
    """
    import unicodedata

    width = 0
    for character in text:
        if unicodedata.combining(character):
            continue
        width += 2 if unicodedata.east_asian_width(character) in ("W", "F") else 1
    return width


def main() -> None:
    """命令行入口：列出录音文件名或检查覆盖情况。

    **为什么要有这个入口**：录音文件名是哈希算出来的，
    让人手写必然出错。给出命令让人直接抄，才不会录完才发现名字不对。
    """
    import argparse

    parser = argparse.ArgumentParser(description="真人录音文件名与覆盖情况")
    parser.add_argument(
        "--list",
        action="store_true",
        help="列出每条参考文本对应的录音文件名",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="检查当前录音覆盖情况",
    )
    parser.add_argument(
        "--eval-dir",
        default="core/eval",
        help="评测集目录",
    )
    parser.add_argument(
        "--recording-dir",
        default=str(DEFAULT_RECORDING_DIR),
        help="真人录音目录",
    )
    args = parser.parse_args()

    eval_dir = Path(args.eval_dir)
    recording_dir = Path(args.recording_dir)
    references = load_eval_references(eval_dir)

    if args.list:
        print(f"共 {len(references)} 条参考文本，录音文件名如下：")
        print()
        for reference in references:
            # **为什么自己算宽度**：print 的字段宽度按字符数算，
            # 而中文是双宽字符 —— 用 print 的对齐会参差不齐。
            padding = " " * max(1, 26 - _display_width(reference))
            print(f"{reference}{padding}-> {recording_name_for(reference)}.wav")
        return

    if args.check:
        counts = describe_recording_coverage(references, recording_dir)
        print(f"录音目录：{recording_dir}")
        print(f"参考文本总数：{len(references)}")
        print(f"已有真人录音：{counts[AudioSource.REAL]} 条")
        print(f"缺录音（将回退 TTS）：{counts[AudioSource.SYNTHETIC]} 条")
        if counts[AudioSource.SYNTHETIC] > 0:
            print()
            print("缺录音的条目：")
            for reference in references:
                if find_recording(reference, recording_dir) is None:
                    print(f"  - {reference} -> {recording_name_for(reference)}.wav")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
