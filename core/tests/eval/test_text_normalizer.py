import pytest

from core.eval.text_normalizer import is_exact_match, normalize_text


def test_trailing_period_is_ignored():
    """识别结果多一个句号不算错 —— 这是纯格式差异。"""
    assert is_exact_match("今天天气真不错", "今天天气真不错。")


def test_internal_comma_is_ignored():
    assert is_exact_match("我最近在准备期末考试", "我最近，在准备期末考试")


def test_whitespace_is_ignored():
    assert is_exact_match("今天天气真不错", "今天 天气 真不错")


def test_full_width_characters_are_converted():
    assert normalize_text("ＡＢＣ") == "ABC"


def test_full_width_space_is_removed():
    assert normalize_text("今天　天气") == "今天天气"


def test_real_error_is_still_detected():
    """归一化不能把真正的识别错误抹平 —— 否则评测就失去意义。"""
    assert not is_exact_match("今天天气真不错", "今天天气真不錯")
    assert not is_exact_match("音量调到50", "音量调到51")


def test_traditional_chinese_is_still_an_error():
    """不转繁简：那是识别错误，必须计入。"""
    assert not is_exact_match("今天天气真不错", "今天天氣真不錯")


def test_empty_text_normalizes_to_empty():
    assert normalize_text("") == ""
    assert normalize_text("。！？ ") == ""


def test_digits_are_preserved():
    assert normalize_text("音量调到50") == "音量调到50"


def test_hyphen_between_digits_is_preserved():
    """连字符不是"该删的标点" —— 删掉会凭空造出参考文本没有的错误。"""
    assert normalize_text("3-4层") == "3-4层"
