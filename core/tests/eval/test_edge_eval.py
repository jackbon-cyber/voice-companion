"""端侧识别评测器的判定逻辑测试。

核心断言四条：
1. **样本不足的条件不参与判定** —— 5 个样本上的 40% 不具统计意义；
2. **门禁只看安静室内条件** —— 端侧 ASR 的职责边界是近场拾音；
3. **判定列与门禁口径一致** —— 报告与退出码依据必须同一集合；
4. **准确率按归一化口径计算**。
"""

from core.eval.edge_eval import (
    GATE_CONDITIONS,
    MIN_SAMPLE_SIZE,
    ConditionResult,
    render_report,
)


def _result(condition: str, correct: int, total: int) -> ConditionResult:
    """构造一个条件结果。

    @param condition 条件名
    @param correct 正确条数
    @param total 总条数
    @return 条件结果
    """
    result = ConditionResult(condition=condition, sample_count=total, correct_count=correct)
    result._rates.extend([0.0] * total)
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


def test_only_clean_condition_is_a_gate_condition():
    """门禁只看安静室内条件 —— 端侧 ASR 的职责边界是近场拾音。"""
    assert GATE_CONDITIONS == ("clean",)


def test_non_gate_conditions_are_reference_only():
    """非门禁条件标注为"参考"，而不是"参与判定"或"样本不足"。"""
    results = {
        "clean": _result("clean", 14, 14),
        "mild": _result("mild", 6, 14),
    }

    report = render_report(results)

    mild_line = next(line for line in report.splitlines() if line.startswith("| mild"))
    assert "仅供参考" in mild_line
    assert "参与判定" not in mild_line


def test_report_states_the_gate_scope_explicitly():
    """报告必须说清哪些条件参与判定、哪些只是参考。

    读者只看一个准确率数字，无法判断它是在什么条件下测的。
    """
    results = {"clean": _result("clean", 14, 14)}

    report = render_report(results)

    assert "口径说明" in report
    assert "门禁只对安静室内条件" in report
    assert "真人语音的噪声鲁棒性尚未验证" in report


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
