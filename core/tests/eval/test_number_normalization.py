import pytest

from core.eval.text_normalizer import is_exact_match, normalize_chinese_numbers


def test_line_number_digit_and_chinese_form_match():
    """读音相同、写法不同不应算识别错误。"""
    assert is_exact_match("地铁三号线最近在修路", "地铁3号线最近在修路")


def test_time_digit_and_chinese_form_match():
    assert is_exact_match("下午三点的会议改到四点了", "下午3点的会议改到4点了")


def test_ordinal_is_normalized():
    assert normalize_chinese_numbers("第三层") == "第3层"


def test_multi_digit_number_is_converted():
    assert normalize_chinese_numbers("二十三") == "23"


def test_single_ten_is_not_converted():
    """单字"十"没有量词佐证，不转 —— 与"一"的处理保持一致。"""
    assert normalize_chinese_numbers("十") == "十"


def test_number_with_measure_word_is_converted():
    assert normalize_chinese_numbers("三层") == "3层"


def test_vague_one_is_not_converted():
    """虚指的"一"不能转 —— "一下""一直"转了就改坏了。"""
    assert normalize_chinese_numbers("一下") == "一下"
    assert normalize_chinese_numbers("一直") == "一直"


def test_ordinal_one_is_converted():
    """序数位上的"一"读作数字，应当转换。"""
    assert normalize_chinese_numbers("第一") == "第1"


def test_real_error_is_still_detected():
    """字错了必须仍然是错。"""
    assert not is_exact_match("刚才电话响了我没听见", "刚才电话想了我没听见")


def test_different_number_is_still_an_error():
    assert not is_exact_match("下午三点的会议", "下午四点的会议")
