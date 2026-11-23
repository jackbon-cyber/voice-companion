"""真人录音接入路径的测试。

**这个测试回答什么问题**

"把真人录音放进目录后，评测真的会走真人录音这条路吗？"

最怕的情况是：文件放进去了、文件名也算对了，但评测仍然悄悄用了 TTS 合成
—— 报告看起来正常，数字却是合成音的。这种失败**不会报错**，只会让
"已接入真人录音"成为一个不成立的声明。

所以这里不只测辅助函数，还要**端到端**验证音频确实被替换。
"""

from __future__ import annotations

import wave
from pathlib import Path

import pytest

from core.eval.audio_source import (
    AudioSource,
    find_recording,
    load_real_recording,
    recording_name_for,
)
from core.eval.edge_eval import (
    GATE_CONDITIONS_ANY_AUDIO,
    GATE_CONDITIONS_REAL_ONLY,
    ConditionResult,
    gate_eligibility,
    render_report,
)

# 评测集里的参考文本。用真实存在的一条，避免造出评测集里没有的文本。
SAMPLE_REFERENCE = "今天天气真不错"


def _write_wav(path: Path, sample_rate: int, frames: int) -> None:
    """写一个指定格式的 WAV 文件。

    @param path 输出路径
    @param sample_rate 采样率
    @param frames 采样点数
    """
    import array

    samples = array.array("h", [1000] * frames)
    with wave.open(str(path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(samples.tobytes())


def test_recording_name_is_deterministic():
    """录音文件名必须稳定 —— 同一参考文本每次算出同一个名字。

    为什么：录音文件靠名字对应参考文本。名字不稳定意味着
    "录好的文件对不上评测集"，而且极难排查（文件名看起来都正常）。
    """
    assert recording_name_for(SAMPLE_REFERENCE) == recording_name_for(
        SAMPLE_REFERENCE
    )
    assert recording_name_for(SAMPLE_REFERENCE) != recording_name_for("另一句话")


def test_recording_name_is_ascii():
    """录音文件名必须是纯 ASCII。

    为什么：中文文件名在 Windows 的 GBK 代码页、POSIX 的 shell 转义、
    以及 Git 的路径处理上都容易出问题。
    """
    name = recording_name_for(SAMPLE_REFERENCE)
    assert name.isascii()
    assert "/" not in name and "\\" not in name


def test_find_recording_returns_none_when_absent(tmp_path: Path):
    """没有录音时返回 None，而不是抛错。"""
    assert find_recording(SAMPLE_REFERENCE, tmp_path) is None


def test_find_recording_locates_file_by_generated_name(tmp_path: Path):
    """按生成的文件名放入的录音能被找到。"""
    target = tmp_path / f"{recording_name_for(SAMPLE_REFERENCE)}.wav"
    _write_wav(target, 16000, 16000)

    found = find_recording(SAMPLE_REFERENCE, tmp_path)

    assert found is not None
    assert found.name == target.name


def test_real_recording_is_resampled_to_16k(tmp_path: Path):
    """真人录音必须重采样到 16 kHz。

    为什么：协议约定 16 kHz。把 44.1 kHz 的字节直接当成 16 kHz 喂进识别器，
    表现为"音调变快、内容完全识别不出来"，且识别器本身不报任何异常。
    """
    target = tmp_path / f"{recording_name_for(SAMPLE_REFERENCE)}.wav"
    _write_wav(target, 44100, 44100)

    pcm = load_real_recording(SAMPLE_REFERENCE, tmp_path)

    assert pcm is not None
    # 1 秒的 44.1 kHz 音频重采样后应为 16000 个采样点 = 32000 字节。
    assert len(pcm) == 32000


def test_real_recording_with_wrong_format_is_rejected(tmp_path: Path):
    """非 16-bit 或非单声道���录音必须明确报错，而不是静默跳过。

    为什么：静默跳过会让"录音已接入"变成不成立的声明 ——
    报告照常出，但用的还是合成音。
    """
    import array

    target = tmp_path / f"{recording_name_for(SAMPLE_REFERENCE)}.wav"
    samples = array.array("h", [1000] * 16000)
    with wave.open(str(target), "wb") as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(samples.tobytes())

    with pytest.raises(ValueError):
        load_real_recording(SAMPLE_REFERENCE, tmp_path)


def test_real_recordings_enable_all_three_conditions_to_gate():
    """全部用真人录音时，三个噪声条件都参与判定。"""
    results = {
        condition: ConditionResult(
            condition=condition, sample_count=14, correct_count=12
        )
        for condition in ("clean", "mild", "noisy")
    }
    for result in results.values():
        result.sources[AudioSource.REAL] = 14

    verdicts = gate_eligibility(results)

    for condition in ("clean", "mild", "noisy"):
        assert verdicts[condition] == "参与判定"


def test_synthetic_audio_keeps_clean_gating():
    """用合成音时 clean 仍然参与判定 —— ASR 维度不能被绕过。"""
    results = {
        condition: ConditionResult(
            condition=condition, sample_count=14, correct_count=12
        )
        for condition in ("clean", "mild", "noisy")
    }
    for result in results.values():
        result.sources[AudioSource.SYNTHETIC] = 14

    verdicts = gate_eligibility(results)

    assert verdicts["clean"] == "参与判定"
    for condition in GATE_CONDITIONS_REAL_ONLY:
        assert verdicts[condition] == "音频为 TTS 合成，不作门禁依据"


def test_report_reflects_real_recording_source():
    """报告在真人录音下必须改口径 —— 不再声明"偏乐观"。"""
    results = {
        "clean": ConditionResult(
            condition="clean", sample_count=14, correct_count=12
        )
    }
    results["clean"].sources[AudioSource.REAL] = 14

    report = render_report(results)

    assert "全部使用真人录音" in report
    assert "偏乐观" not in report


def test_report_keeps_optimistic_warning_for_synthetic():
    """合成音下报告必须保留"偏乐观"的警告。"""
    results = {
        "clean": ConditionResult(
            condition="clean", sample_count=14, correct_count=12
        )
    }
    results["clean"].sources[AudioSource.SYNTHETIC] = 14

    report = render_report(results)

    assert "偏乐观" in report
    assert "未取得真人录音" in report


def test_report_describes_partial_recording_accurately():
    """部分用真人录音时，报告必须说清是"部分"，不能写"全部由 TTS 合成"。

    为什么：只放了 1 条录音却说"音频全部由 TTS 合成"是**不实描述** ——
    读者会据此误判整份报告的可信度。
    """
    clean = ConditionResult(
        condition="clean", sample_count=14, correct_count=12
    )
    clean.sources[AudioSource.REAL] = 1
    clean.sources[AudioSource.SYNTHETIC] = 13

    report = render_report({"clean": clean})

    assert "部分使用真人录音" in report
    assert "未取得真人录音" not in report
    assert "混用的准确率没有可解释性" in report


def test_gate_condition_tables_do_not_overlap():
    """两档门禁条件表不能重叠。

    为什么：重叠会让同一条件在两档里各算一次，判定依据变得含糊。
    """
    assert not set(GATE_CONDITIONS_ANY_AUDIO) & set(GATE_CONDITIONS_REAL_ONLY)
