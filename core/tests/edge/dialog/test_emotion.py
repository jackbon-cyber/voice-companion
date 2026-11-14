from core.edge.dialog.emotion import (
    DEFAULT_EMOTION,
    EMOTION_TAGS,
    detect_emotion,
)


def test_positive_expression_detected_as_joy():
    assert detect_emotion("今天太开心了") == "joy"


def test_negative_expression_detected_as_sadness():
    assert detect_emotion("今天真的好难过") == "sadness"


def test_anger_expression_detected():
    assert detect_emotion("真是气死我了") == "anger"


def test_fear_expression_detected():
    assert detect_emotion("我有点害怕") == "fear"


def test_surprise_expression_detected():
    assert detect_emotion("没想到你也在") == "surprise"


def test_tenderness_expression_detected():
    assert detect_emotion("好想你") == "tenderness"


def test_encouragement_expression_detected():
    assert detect_emotion("加油，你可以的") == "encouragement"


def test_plain_text_falls_back_to_default():
    assert detect_emotion("嗯……那个……") == DEFAULT_EMOTION


def test_empty_text_falls_back_to_default():
    assert detect_emotion("") == DEFAULT_EMOTION


def test_longer_keyword_wins_over_shorter_one():
    """"不开心"（sadness）比"开心"（joy）更长，命中更长词才是准确的那个。"""
    assert detect_emotion("今天不开心") == "sadness"


def test_single_character_noise_does_not_trigger_emotion():
    """单字"喜"不应命中 joy：它会命中"喜欢"这类无关表达。"""
    assert detect_emotion("我很喜欢这个设计") == DEFAULT_EMOTION


def test_all_detected_tags_are_within_declared_set():
    """判定结果必须落在协议声明的情感枚举内，否则下行回复会被云端拒收。"""
    samples = [
        "太开心了",
        "好难过",
        "气死了",
        "我害怕",
        "没想到",
        "想你",
        "加油",
        "随便说点什么",
    ]
    for sample in samples:
        assert detect_emotion(sample) in EMOTION_TAGS
