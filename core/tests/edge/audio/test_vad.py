from core.edge.audio.vad import VoiceActivityDetector


def test_both_thresholds_must_pass():
    detector = VoiceActivityDetector(speech_probability_threshold=0.6, energy_threshold=0.01)
    assert detector.is_speech(0.7, 0.02) is True
    assert detector.is_speech(0.5, 0.02) is False
    assert detector.is_speech(0.7, 0.005) is False
