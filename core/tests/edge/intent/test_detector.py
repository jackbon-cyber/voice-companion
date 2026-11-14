from core.edge.intent.detector import UNKNOWN_INTENT, IntentDetector
from core.edge.intent.rules import DEFAULT_RULES


def test_rule_match_is_handled_locally():
    decision = IntentDetector().detect("把音量调到五十", 0.9)
    assert decision.intent == "set_volume"
    assert decision.handled_locally is True


def test_unknown_expression_is_not_handled_locally():
    decision = IntentDetector().detect("今天发生了好多事情啊", 0.9)
    assert decision.intent == UNKNOWN_INTENT
    assert decision.handled_locally is False


def test_low_confidence_with_keyword_falls_back_to_rules():
    decision = IntentDetector().detect("播放音乐", 0.2)
    assert decision.intent == "play_music"
    assert decision.handled_locally is True


def test_low_confidence_without_keyword_is_rejected():
    decision = IntentDetector().detect("嗯……那个……", 0.2)
    assert decision.handled_locally is False


def test_default_rules_cover_fixed_commands():
    intents = {rule.intent for rule in DEFAULT_RULES}
    assert {"set_volume", "stop_speaking", "play_music"} <= intents


def test_stop_keyword_does_not_match_ordinary_sentence():
    decision = IntentDetector().detect("停下来休息一下", 0.9)
    assert decision.intent != "stop_speaking"
    assert decision.handled_locally is False


def test_stop_keyword_does_not_match_negated_phrase():
    decision = IntentDetector().detect("别停下来", 0.9)
    assert decision.intent != "stop_speaking"


def test_explicit_stop_command_is_recognized():
    decision = IntentDetector().detect("别说了", 0.9)
    assert decision.intent == "stop_speaking"
    assert decision.handled_locally is True
