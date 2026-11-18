"""模型包 manifest schema 的契约测试。

模型包是**分发产物的格式**：打包脚本产出它，设备端安装它。
schema 一旦与打包脚本漂移，表现是"打包出来的包设备端装不上" ——
而设备端在真机上，出错时无法快速定位。

因此这里把 schema 钉在可断言的规则上：哪些字段必填、哪些取值被禁止。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

# 仓库根。测试位于 core/tests/device_ref/，仓库根在其上三层。
REPO_ROOT = Path(__file__).resolve().parents[3]

# 模型包 schema 路径。
MANIFEST_SCHEMA_PATH = REPO_ROOT / "device-ref" / "model-package" / "manifest.schema.json"


def _load_schema() -> dict:
    """加载模型包 schema。

    @return schema 字典
    """
    return json.loads(MANIFEST_SCHEMA_PATH.read_text(encoding="utf-8"))


def _validator() -> Draft202012Validator:
    """构造 schema 校验器。

    @return 校验器
    """
    return Draft202012Validator(_load_schema())


def _valid_manifest() -> dict:
    """构造一份合法的 manifest。

    @return manifest 字典
    """
    return {
        "packageVersion": "1.4.0",
        "platform": "stm32mpu257",
        "models": [
            {
                "id": "llm_lora_0_5b",
                "version": "3",
                "file": "models/llm_lora_0_5b.q4_k_m.gguf",
                "size": 419430400,
                "sha256": "a" * 64,
                "minRuntime": "1.2.0",
            }
        ],
        "compat": {"firmwareMin": "2.1.0", "firmwareMax": "2.9.0"},
        "rollbackPartition": "B",
        "signatureAlgorithm": "Ed25519",
        "signatureFile": "signature.sig",
    }


def test_manifest_schema_file_exists():
    """模型包 schema 必须存在。"""
    assert MANIFEST_SCHEMA_PATH.exists(), f"模型包 schema 缺失：{MANIFEST_SCHEMA_PATH}"


def test_manifest_schema_is_valid_draft_2020_12():
    """schema 本身必须是合法的 JSON Schema。"""
    Draft202012Validator.check_schema(_load_schema())


def test_valid_manifest_passes():
    """一份完整且合法的 manifest 必须通过校验。"""
    errors = sorted(_validator().iter_errors(_valid_manifest()), key=lambda e: list(e.absolute_path))
    assert not errors, "合法 manifest 不应报错：" + "; ".join(error.message for error in errors)


@pytest.mark.parametrize(
    "missing_field",
    ["packageVersion", "platform", "models", "compat", "rollbackPartition"],
)
def test_manifest_requires_identity_fields(missing_field: str):
    """缺少身份与兼容信息的 manifest 必须非法。

    为什么这五项必填：前两项说明"这是什么、给谁用"，
    后三项说明"能不能装、装失败退到哪" —— 缺任何一项，设备端都无法安全安装。
    """
    manifest = _valid_manifest()
    del manifest[missing_field]

    errors = list(_validator().iter_errors(manifest))
    assert errors, f"缺少 {missing_field} 时必须报错"


@pytest.mark.parametrize(
    "missing_field",
    ["id", "version", "file", "size", "sha256"],
)
def test_manifest_model_entry_requires_integrity_fields(missing_field: str):
    """模型条目必须自带完整性与版本信息。

    为什么 sha256 必填：没有校验和的模型文件，设备端无法判断下载是否损坏 ——
    装上一个截断的模型，表现为"模型加载失败"，排查方向完全跑偏。
    """
    manifest = _valid_manifest()
    del manifest["models"][0][missing_field]

    errors = list(_validator().iter_errors(manifest))
    assert errors, f"模型条目缺少 {missing_field} 时必须报错"


def test_manifest_rejects_short_sha256():
    """sha256 必须是 64 位十六进制。"""
    manifest = _valid_manifest()
    manifest["models"][0]["sha256"] = "abc123"

    errors = list(_validator().iter_errors(manifest))
    assert errors, "非 64 位的 sha256 必须报错"


def test_manifest_rejects_negative_size():
    """模型大小不得为负。"""
    manifest = _valid_manifest()
    manifest["models"][0]["size"] = -1

    errors = list(_validator().iter_errors(manifest))
    assert errors, "负数大小必须报错"


def test_manifest_requires_models_not_empty():
    """模型列表不得为空 —— 空包没有安装价值。"""
    manifest = _valid_manifest()
    manifest["models"] = []

    errors = list(_validator().iter_errors(manifest))
    assert errors, "空模型列表必须报错"


def test_rollback_partition_must_be_a_or_b():
    """回滚分区只能是 A 或 B。

    为什么必须收紧为枚举：自由字符串下，写成 "C" 或 "a" 都不会报错，
    而设备端会把它当成"回滚到未知分区" —— 回滚路径失效。
    """
    manifest = _valid_manifest()
    manifest["rollbackPartition"] = "C"

    errors = list(_validator().iter_errors(manifest))
    assert errors, "非法回滚分区必须报错"


def test_signature_algorithm_must_be_known():
    """验签算法必须是已知算法。

    为什么必须收紧：算法名写错时，设备端"用未知算法验签"，
    表现是"签名无效" —— 但真实原因是算法名拼错，排查会被带偏。
    """
    manifest = _valid_manifest()
    manifest["signatureAlgorithm"] = "ROT13"

    errors = list(_validator().iter_errors(manifest))
    assert errors, "未知验签算法必须报错"


def test_firmware_range_ordering_is_documented_as_script_enforced():
    """固件版本区间的先后顺序**不由 schema 校验**。

    为什么：JSON Schema Draft 2020-12 没有跨字段的语义化版本比较能力，
    ``firmwareMin > firmwareMax`` 这类约束无法用 schema 表达。
    强行用 pattern 近似（比如比较字典序）会在带预发布标识的版本号上出错，
    比不校验更糟。

    因此该不变量由**打包脚本**强制（见 ``test_package_model.py``），
    schema 只保证两个字段都是合法的版本号形态。
    这里钉住"schema 不得假装能管这件事"——
    防止有人后来加一个基于字典序的 pattern，那是看起来有校验、实则错误的做法。
    """
    schema = _load_schema()

    firmware_min = schema["properties"]["compat"]["properties"]["firmwareMin"]
    firmware_max = schema["properties"]["compat"]["properties"]["firmwareMax"]

    # 两个字段的 pattern 必须一致 —— 不一致的 pattern 意味着"下界与上界用不同口径比较"。
    assert firmware_min["pattern"] == firmware_max["pattern"]
    # 且必须只约束形态，不含任何顺序相关的构造。
    assert "const" not in firmware_min
    assert "enum" not in firmware_min


def test_manifest_rejects_unknown_fields():
    """未知字段必须被拒绝。

    与协议 schema 同一条理由：多出的字段说明打包端与设备端版本已错位，
    静默忽略会让错位无法被发现。
    """
    manifest = _valid_manifest()
    manifest["unexpectedField"] = "something"

    errors = list(_validator().iter_errors(manifest))
    assert errors, "未知字段必须报错"
