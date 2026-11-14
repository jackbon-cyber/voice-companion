import pytest

from core.edge.dialog.factual import (
    FACTUAL_GUIDANCE_PHRASES,
    FactualCategory,
    FactualGuard,
    FactualRequestDetector,
)


def test_ordinary_chat_is_not_factual():
    detector = FactualRequestDetector()

    request = detector.detect("今天好累啊")

    assert request.is_factual is False
    assert request.category is None


def test_personal_fact_is_detected():
    detector = FactualRequestDetector()

    request = detector.detect("还记得我上次说的那件事吗")

    assert request.is_factual is True
    assert request.category is FactualCategory.PERSONAL_FACT


def test_numeric_fact_is_detected():
    detector = FactualRequestDetector()

    request = detector.detect("这个药一次吃多少毫克合适")

    assert request.is_factual is True
    assert request.category is FactualCategory.NUMERIC_FACT


def test_realtime_fact_is_detected():
    detector = FactualRequestDetector()

    request = detector.detect("今天天气怎么样")

    assert request.is_factual is True
    assert request.category is FactualCategory.REALTIME_FACT


def test_empty_text_is_not_factual():
    detector = FactualRequestDetector()

    assert detector.detect("").is_factual is False


def test_guard_sends_factual_request_to_cloud():
    guard = FactualGuard()

    result = guard.check("这个药一次吃多少毫克")

    assert result.should_go_to_cloud is True
    assert result.category is FactualCategory.NUMERIC_FACT


def test_guard_does_not_send_ordinary_chat_to_cloud():
    guard = FactualGuard()

    result = guard.check("陪我聊会儿天")

    assert result.should_go_to_cloud is False
    assert result.guidance is None


def test_guidance_phrase_contains_no_factual_content():
    """引导话术不得包含具体事实 —— 它的作用是引导上云，不是替代回答。"""
    guard = FactualGuard()

    result = guard.check("今天天气怎么样")

    assert result.guidance is not None
    assert result.guidance in FACTUAL_GUIDANCE_PHRASES
    for marker in ("°", "度", "毫米", "元"):
        assert marker not in result.guidance


def test_guidance_is_none_for_non_factual():
    detector = FactualRequestDetector()

    assert detector.guidance_phrase(detector.detect("你好呀")) is None


def test_custom_keyword_table_is_used():
    detector = FactualRequestDetector(
        keyword_table={FactualCategory.TIME_FACT: ("宇宙历",)}
    )

    assert detector.detect("宇宙历几号").is_factual is True
    assert detector.detect("今天天气怎么样").is_factual is False


def test_guard_result_records_note():
    guard = FactualGuard()

    result = guard.check("还记得吗")

    assert result.notes
