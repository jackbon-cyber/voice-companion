import numpy as np
import pytest

from core.edge.asr.recognizer import build_prompt_text


def test_prompt_contains_hotwords_when_present():
    prompt = build_prompt_text(["小天", "小蓝"])

    assert "小天" in prompt
    assert "小蓝" in prompt


def test_prompt_without_hotwords_still_declares_mandarin():
    """即使没有热词，也必须声明普通话 —— 否则模型会输出繁体。

    Whisper 的中文训练数据里繁体占比很高，不给简体偏置时
    "今天天气真不错"会被识别成"今天天氣真不錯"。
    对陪伴机器人而言这是**功能性缺陷**而不是观感问题：
    下游的关键词意图匹配会全部失效。
    """
    prompt = build_prompt_text([])

    assert "普通话" in prompt


def test_prompt_without_hotwords_is_not_blank():
    prompt = build_prompt_text([])

    assert prompt.strip() != ""


def test_prompt_with_empty_hotword_entries_is_ignored():
    prompt = build_prompt_text(["", "  "])

    assert prompt.strip() != ""
