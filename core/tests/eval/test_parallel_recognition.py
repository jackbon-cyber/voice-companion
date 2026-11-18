"""并行识别的行为测试。

核心断言：**并行结果与串行完全一致**。
识别顺序变化会让报告在两次运行之间产生 diff，破坏可复现性，
所以"结果顺序必须与输入顺序一一对应"不是优化细节，是硬要求。
"""

from core.eval.edge_eval import MAX_RECOGNITION_WORKERS, recognize_all


class _FakeRecognizer:
    """假的识别器：按音频内容里的标记返回文本，并记录调用次数。"""

    def __init__(self) -> None:
        self.calls: list[bytes] = []

    def transcribe(self, pcm: bytes):
        """返回带序号的识别结果。

        @param pcm 音频字节
        @return 识别结果
        """
        self.calls.append(pcm)
        marker = pcm[:1].decode("ascii", errors="ignore")
        return type("_Result", (), {"text": f"text-{marker}"})()


def test_empty_input_returns_empty_list():
    assert recognize_all(_FakeRecognizer(), []) == []


def test_single_sample_is_processed():
    recognizer = _FakeRecognizer()

    result = recognize_all(recognizer, [b"a"])

    assert result == ["text-a"]
    assert len(recognizer.calls) == 1


def test_parallel_result_order_matches_input_order():
    """并行执行的完成顺序不确定，但输出顺序必须与输入一致。"""
    chunks = [bytes([ord("a") + index]) for index in range(20)]

    result = recognize_all(_FakeRecognizer(), chunks)

    assert result == [f"text-{chr(ord('a') + index)}" for index in range(20)]


def test_all_samples_are_recognized():
    recognizer = _FakeRecognizer()
    chunks = [bytes([ord("a") + index]) for index in range(20)]

    recognize_all(recognizer, chunks)

    assert len(recognizer.calls) == 20


def test_worker_count_is_bounded():
    """外层线程数必须有上限：ctranslate2 推理本身已多线程，外层再放开会争抢。"""
    assert 1 <= MAX_RECOGNITION_WORKERS <= 16
