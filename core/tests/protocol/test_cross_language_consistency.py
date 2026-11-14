"""跨语言契约一致性测试：Python 侧对共享样例的判定。

Java 侧在 ``ProtocolValidatorTest`` 里读**同一份** ``samples.json``，
断言两侧对每条样例的判定结论完全一致。

这是端云契约的真正护栏：两份 schema 迟早会漂移，而漂移的表现是
"某些消息端侧认为合法、云端认为非法"，排查成本极高。
"""

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from core.protocol.loader import load_schema

REPO_ROOT = Path(__file__).resolve().parents[3]
SAMPLES_PATH = (
    REPO_ROOT / "core" / "cloud" / "src" / "test" / "resources" / "protocol-samples" / "samples.json"
)


def _samples() -> list[dict]:
    """读取共享的协议样例。

    @return 样例列表
    """
    return json.loads(SAMPLES_PATH.read_text(encoding="utf-8"))["samples"]


def test_samples_file_exists():
    assert SAMPLES_PATH.exists(), f"共享样例文件缺失：{SAMPLES_PATH}"


@pytest.mark.parametrize("sample", _samples(), ids=lambda s: f"{s['schema']}:{s['note']}")
def test_python_validator_matches_expected_verdict(sample):
    validator = Draft202012Validator(load_schema(sample["schema"]))
    assert validator.is_valid(sample["payload"]) is sample["valid"], sample["note"]


@pytest.mark.parametrize("sample", _samples(), ids=lambda s: f"{s['schema']}:{s['note']}")
def test_python_validator_rejects_invalid_samples(sample):
    if sample["valid"]:
        pytest.skip("有效样例")
    validator = Draft202012Validator(load_schema(sample["schema"]))
    assert not validator.is_valid(sample["payload"])
