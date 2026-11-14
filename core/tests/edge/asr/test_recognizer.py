from core.edge.asr.recognizer import NullRecognizer, RecognitionResult, is_confident


def test_null_recognizer_returns_empty_result():
    result = NullRecognizer().transcribe(b"\x00" * 640)
    assert result.text == ""
    assert result.confidence == 0.0


def test_is_confident_rejects_empty_text_even_with_high_confidence():
    assert is_confident(RecognitionResult("", 0.99, "zh")) is False


def test_is_confident_accepts_above_threshold():
    assert is_confident(RecognitionResult("今天天气不错", 0.8, "zh")) is True


def test_is_confident_rejects_below_threshold():
    assert is_confident(RecognitionResult("今天天气不错", 0.3, "zh")) is False
