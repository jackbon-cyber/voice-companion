"""端侧识别评测器的判定逻辑测试。

核心断言：
1. **样本不足的条件不参与判定** —— 5 个样本上的 40% 不具统计意义；
2. **门禁分两档** —— clean 任何音频都判；mild/noisy 仅真人录音才判；
3. **判定列与门禁口径一致** —— 报告与退出码依据必须同一集合；
4. **准确率按归一化口径计算**；
5. **报告必须写明音频来源** —— 读者要知道这个数字是在什么音频上测的。
"""

from core.eval.audio_source import AudioSource
from core.eval.edge_eval import (
    GATE_CONDITIONS_ANY_AUDIO,
    GATE_CONDITIONS_REAL_ONLY,
    MIN_SAMPLE_SIZE,
    ConditionResult,
    gate_eligibility,
    render_report,
)


def _result(
    condition: str,
    correct: int,
    total: int,
    source: AudioSource = AudioSource.SYNTHETIC,
) -> ConditionResult:
    """构造一个条件结果。

    @param condition 条件名
    @param correct 正确条数
    @param total 总条数
    @param source 音频来源
    @return 条件结果
    """
    result = ConditionResult(condition=condition, sample_count=total, correct_count=correct)
    result._rates.extend([0.0] * total)
    result.sources[source] = total
    return result


def test_insufficient_samples_do_not_participate_in_verdict():
    """样本不足的条件不参与判定，即使它的准确率最低。

    这里刻意让 clean（100%）高于 mild（60%），而 noisy 只有 5 条（20%）：
    若实现错误地把样本不足的条件也纳入判定，最差条件就会变成 noisy。
    """
    results = {
        "clean": _result("clean", 14, 14),
        "mild": _result("mild", 6, 10),
        "noisy": _result("noisy", 1, 5),
    }

    report = render_report(results)

    assert "判定条件 clean" in report
    assert "判定条件 noisy" not in report


def test_clean_is_a_gate_condition_for_any_audio():
    """clean 是任何音频都参与判定的条件。

    为什么：合成音在安静室内条件下仍是有意义的**下界** ——
    连合成音都识别不了，真人语音只会更差。
    若因为没有真人录音就连 clean 也不判，ASR 维度实际上被绕过了。
    """
    assert GATE_CONDITIONS_ANY_AUDIO == ("clean",)


def test_noise_conditions_require_real_recordings():
    """mild / noisy 仅在用真人录音时才参与判定。

    为什么：合成音缺少真人的音高变化与共振峰细节，属于分布外输入，
    它在噪声下的表现既不代表真人语音、也不能用来判定模型能力。
    """
    assert GATE_CONDITIONS_REAL_ONLY == ("mild", "noisy")


def test_synthetic_audio_does_not_gate_noise_conditions():
    """用合成音时，噪声条件标注为"不作门禁依据"，而不是"参与判定"。"""
    results = {
        "clean": _result("clean", 14, 14),
        "mild": _result("mild", 10, 14),
    }

    report = render_report(results)

    mild_line = next(line for line in report.splitlines() if line.startswith("| mild"))
    assert "不作门禁依据" in mild_line
    assert "参与判定" not in mild_line


def test_real_recordings_enable_noise_conditions_to_gate():
    """用真人录音时，噪声条件参与判定。"""
    results = {
        "clean": _result("clean", 14, 14, AudioSource.REAL),
        "mild": _result("mild", 12, 14, AudioSource.REAL),
    }

    report = render_report(results)

    mild_line = next(line for line in report.splitlines() if line.startswith("| mild"))
    assert "参与判定" in mild_line


def test_mixed_audio_does_not_enable_noise_conditions():
    """真人与合成音混用时，噪声条件仍不作门禁依据。

    为什么：混着算出的准确率既不代表真人语音、也不代表合成音 ——
    这个数字没有可解释性。
    """
    clean = ConditionResult(condition="clean", sample_count=14, correct_count=14)
    clean.sources[AudioSource.REAL] = 7
    clean.sources[AudioSource.SYNTHETIC] = 7
    mild = _result("mild", 12, 14, AudioSource.SYNTHETIC)

    verdicts = gate_eligibility({"clean": clean, "mild": mild})

    assert verdicts["mild"] == "音频为 TTS 合成，不作门禁依据"


def test_gate_eligibility_and_report_agree():
    """判定函数与报告的判定列必须完全一致。

    为什么：报告说"参与判定"的条件集合与退出码依据必须同一集合，
    否则会出现"报告说不参与判定，退出码却按它判失败"。
    """
    results = {
        "clean": _result("clean", 14, 14),
        "mild": _result("mild", 12, 14),
        "noisy": _result("noisy", 13, 14),
    }

    verdicts = gate_eligibility(results)
    report = render_report(results)

    for condition, verdict in verdicts.items():
        line = next(
            row for row in report.splitlines() if row.startswith(f"| {condition} ")
        )
        if verdict == "参与判定":
            assert "参与判定" in line
        elif "不作门禁依据" in verdict:
            assert "不作门禁依据" in line
        elif "样本不足" in verdict:
            assert "样本不足" in line


def test_report_states_the_gate_scope_explicitly():
    """报告必须说清哪些条件参与判定、哪些只是参考。

    读者只看一个准确率数字，无法判断它是在什么条件下测的。
    """
    results = {"clean": _result("clean", 14, 14)}

    report = render_report(results)

    assert "口径说明" in report
    assert "真人语音的噪声鲁棒性" in report


def test_report_shows_audio_source_per_condition():
    """报告必须标注每条样本的音频来源。

    为什么：一个准确率数字若不说明是在真人语音还是合成音上测的，
    读者无法判断它能不能代表真实体验。
    """
    results = {
        "clean": _result("clean", 14, 14, AudioSource.REAL),
        "mild": _result("mild", 12, 14),
    }

    report = render_report(results)

    clean_line = next(line for line in report.splitlines() if line.startswith("| clean"))
    mild_line = next(line for line in report.splitlines() if line.startswith("| mild"))
    assert "真人录音" in clean_line
    assert "TTS 合成" in mild_line


def test_verdict_column_marks_participating_conditions():
    """样本充足且是门禁条件的行显示"参与判定"。"""
    results = {
        "clean": _result("clean", 14, 14),
        "noisy": _result("noisy", 1, 5),
    }

    report = render_report(results)

    clean_line = next(line for line in report.splitlines() if line.startswith("| clean"))
    noisy_line = next(line for line in report.splitlines() if line.startswith("| noisy"))

    assert "参与判定" in clean_line
    assert "样本不足" not in clean_line
    assert "样本不足" in noisy_line


def test_failing_condition_with_enough_samples_fails_the_gate():
    """样本充足且准确率低于阈值 → 判定不通过。"""
    results = {"clean": _result("clean", 6, 10)}

    report = render_report(results)

    assert "不通过" in report


def test_passing_condition_with_enough_samples_passes_the_gate():
    results = {"clean": _result("clean", 10, 10)}

    report = render_report(results)

    assert "**总体结论：通过**" in report


def test_no_condition_with_enough_samples_means_no_verdict():
    """所有条件样本都不足时，不给出通过/不通过的结论。"""
    results = {"clean": _result("clean", 1, 5)}

    report = render_report(results)

    assert "不参与门禁判定" in report


def test_min_sample_size_is_positive():
    assert MIN_SAMPLE_SIZE > 0
