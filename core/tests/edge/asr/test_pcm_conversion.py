import numpy as np
import pytest

from core.edge.asr.recognizer import pcm_to_float32


def test_pcm_conversion_normalizes_to_signed_range():
    """16-bit 有符号 PCM 应归一化到 [-1, 1] 的浮点区间。

    归一化必须是除以 32768 而不是 32767：Whisper 的特征提取器假定输入
    满幅为 1.0，用 32767 会让峰值略大于 1，对短音频的静音检测有影响。
    """
    samples = pcm_to_float32(np.array([0, 32767, -32768], dtype=np.int16))

    assert samples[0] == pytest.approx(0.0)
    assert samples[1] == pytest.approx(32767 / 32768)
    assert samples[2] == pytest.approx(-1.0)


def test_pcm_conversion_of_empty_input_is_empty():
    samples = pcm_to_float32(np.array([], dtype=np.int16))

    assert samples.shape == (0,)
