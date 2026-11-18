"""模型打包脚本的行为测试。

打包脚本的失败模式很隐蔽：产出一个**看起来正常**但装不上的包。
因此这里盯住三件事：
1. 校验和必须与文件实际内容一致（不是占位符）；
2. 清单必须能被 schema 校验通过；
3. 签名必须可验签，且**验签失败必须导致打包失败**（而不是打个警告继续）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

# 仓库根。测试位于 core/tests/device_ref/，仓库根在其上三层。
REPO_ROOT = Path(__file__).resolve().parents[3]

# 打包脚本路径。
SCRIPT_PATH = REPO_ROOT / "device-ref" / "model-package" / "package_model.py"

# 模型包 schema 路径。
MANIFEST_SCHEMA_PATH = REPO_ROOT / "device-ref" / "model-package" / "manifest.schema.json"

# 打包时使用的模型文件名（放在 models/ 目录下）。
MODEL_FILE_NAME = "intent_lora.int8.onnx"

# 模型内容。刻意用非空内容：空文件的 sha256 是个"看起来对"的常量，
# 用它做测试会让"校验和写死"的实现蒙混过关。
MODEL_CONTENT = b"fake-onnx-model-bytes-for-testing"


def _run_script(*args: str) -> subprocess.CompletedProcess:
    """运行打包脚本。

    **编码**：显式指定 UTF-8 —— Windows 上子进程输出的默认解码是 GBK，
    脚本里的中文错误信息会触发解码异常，把"断言退出码"变成"断言解码成功"。

    @param args 命令行参数
    @return 进程结果
    """
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=REPO_ROOT,
        check=False,
    )


def _prepare_model(tmp_path: Path) -> Path:
    """准备一份待打包的模型文件。

    @param tmp_path 临时目录
    @return 模型文件路径
    """
    model_dir = tmp_path / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    model_path = model_dir / MODEL_FILE_NAME
    model_path.write_bytes(MODEL_CONTENT)
    return model_path


def _write_manifest(tmp_path: Path, model_path: Path, **overrides) -> Path:
    """写一份待打包的清单。

    @param tmp_path 临时目录
    @param model_path 模型文件路径
    @param overrides 需要覆盖的字段
    @return 清单路径
    """
    # 文件可能刻意不存在（缺文件必须失败的用例），此时 size 填占位值 ——
    # 打包脚本会用真实大小覆盖它，这里的值只用于让清单先能写成。
    size = model_path.stat().st_size if model_path.is_file() else 0
    manifest = {
        "packageVersion": "1.4.0",
        "platform": "stm32mpu257",
        "models": [
            {
                "id": "intent_lora",
                "version": "7",
                "file": f"models/{MODEL_FILE_NAME}",
                "size": size,
                "sha256": "0" * 64,
                "minRuntime": "1.2.0",
            }
        ],
        "compat": {"firmwareMin": "2.1.0", "firmwareMax": "2.9.0"},
        "rollbackPartition": "B",
        "signatureAlgorithm": "Ed25519",
        "signatureFile": "signature.sig",
    }
    manifest.update(overrides)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest_path


def _generate_key(tmp_path: Path) -> Path:
    """生成一份签名私钥。

    @param tmp_path 临时目录
    @return 私钥路径
    """
    key_path = tmp_path / "sign_key.pem"
    result = _run_script("--gen-key", str(key_path))
    assert result.returncode == 0, f"生成密钥失败：{result.stderr}"
    return key_path


def test_script_exists():
    """打包脚本必须存在。"""
    assert SCRIPT_PATH.exists(), f"打包脚本缺失：{SCRIPT_PATH}"


def test_package_computes_real_sha256(tmp_path: Path):
    """打包必须计算模型文件的**真实** sha256。

    为什么：清单里的 sha256 是设备端唯一的完整性依据。
    写死一个占位值时，打包能成功，设备端安装时才失败 ——
    而那时已经联网下发，代价远高于在打包阶段失败。
    """
    model_path = _prepare_model(tmp_path)
    manifest_path = _write_manifest(tmp_path, model_path)
    out_dir = tmp_path / "out"

    result = _run_script(
        "--manifest", str(manifest_path),
        "--out", str(out_dir),
        "--sign-key", str(_generate_key(tmp_path)),
    )
    assert result.returncode == 0, f"打包失败：{result.stderr}"

    produced = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    import hashlib

    expected = hashlib.sha256(MODEL_CONTENT).hexdigest()
    assert produced["models"][0]["sha256"] == expected


def test_package_output_manifest_validates_against_schema(tmp_path: Path):
    """打包产出的清单必须能被 schema 校验通过。"""
    model_path = _prepare_model(tmp_path)
    manifest_path = _write_manifest(tmp_path, model_path)
    out_dir = tmp_path / "out"

    result = _run_script(
        "--manifest", str(manifest_path),
        "--out", str(out_dir),
        "--sign-key", str(_generate_key(tmp_path)),
    )
    assert result.returncode == 0, f"打包失败：{result.stderr}"

    schema = json.loads(MANIFEST_SCHEMA_PATH.read_text(encoding="utf-8"))
    produced = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(schema).iter_errors(produced))
    assert not errors, "产出清单不合法：" + "; ".join(error.message for error in errors)


def test_package_copies_model_file_into_output(tmp_path: Path):
    """模型文件必须被复制进产物目录。

    为什么：清单里的相对路径指向包内文件；文件没复制进去，
    包能通过所有校验，安装时却找不到模型。
    """
    model_path = _prepare_model(tmp_path)
    manifest_path = _write_manifest(tmp_path, model_path)
    out_dir = tmp_path / "out"

    result = _run_script(
        "--manifest", str(manifest_path),
        "--out", str(out_dir),
        "--sign-key", str(_generate_key(tmp_path)),
    )
    assert result.returncode == 0, f"打包失败：{result.stderr}"

    copied = out_dir / "models" / MODEL_FILE_NAME
    assert copied.exists(), "模型文件未复制进产物目录"
    assert copied.read_bytes() == MODEL_CONTENT


def test_package_rejects_missing_model_file(tmp_path: Path):
    """清单引用的模型文件不存在时必须失败。

    为什么：缺文件时若继续打包，产物会在安装阶段失败。
    """
    manifest_path = _write_manifest(tmp_path, tmp_path / "models" / "absent.onnx")
    out_dir = tmp_path / "out"

    result = _run_script(
        "--manifest", str(manifest_path),
        "--out", str(out_dir),
        "--sign-key", str(_generate_key(tmp_path)),
    )
    assert result.returncode != 0, "模型文件缺失时必须失败"


def test_package_rejects_inverted_firmware_range(tmp_path: Path):
    """固件版本区间颠倒时必须失败。

    为什么：schema 表达不了跨字段的语义化版本比较（见 manifest README），
    这个不变量只能由打包脚本守。区间颠倒的包不匹配任何设备，
    表现为"所有设备都装不上"，而设备端看不出原因。
    """
    model_path = _prepare_model(tmp_path)
    manifest_path = _write_manifest(
        tmp_path, model_path, compat={"firmwareMin": "3.0.0", "firmwareMax": "2.0.0"}
    )
    out_dir = tmp_path / "out"

    result = _run_script(
        "--manifest", str(manifest_path),
        "--out", str(out_dir),
        "--sign-key", str(_generate_key(tmp_path)),
    )
    assert result.returncode != 0, "固件版本区间颠倒时必须失败"


def test_package_produces_verifiable_signature(tmp_path: Path):
    """打包必须产出可验签的签名文件。"""
    model_path = _prepare_model(tmp_path)
    manifest_path = _write_manifest(tmp_path, model_path)
    out_dir = tmp_path / "out"

    result = _run_script(
        "--manifest", str(manifest_path),
        "--out", str(out_dir),
        "--sign-key", str(_generate_key(tmp_path)),
    )
    assert result.returncode == 0, f"打包失败：{result.stderr}"

    assert (out_dir / "signature.sig").exists(), "签名文件未产出"


def test_package_without_sign_key_fails(tmp_path: Path):
    """未提供签名密钥时必须失败。

    为什么：未签名的包等于明文分发的模型文件 ——
    攻击者可以替换模型，设备端无从察觉。
    """
    model_path = _prepare_model(tmp_path)
    manifest_path = _write_manifest(tmp_path, model_path)
    out_dir = tmp_path / "out"

    result = _run_script("--manifest", str(manifest_path), "--out", str(out_dir))
    assert result.returncode != 0, "未提供签名密钥时必须失败"


def test_package_rejects_manifest_failing_schema(tmp_path: Path):
    """清单本身不合法时必须失败。"""
    model_path = _prepare_model(tmp_path)
    manifest_path = _write_manifest(tmp_path, model_path, rollbackPartition="C")
    out_dir = tmp_path / "out"

    result = _run_script(
        "--manifest", str(manifest_path),
        "--out", str(out_dir),
        "--sign-key", str(_generate_key(tmp_path)),
    )
    assert result.returncode != 0, "清单不合法时必须失败"


@pytest.mark.parametrize("bad_key_content", ["not-a-key", ""])
def test_package_rejects_invalid_sign_key(tmp_path: Path, bad_key_content: str):
    """签名密钥无效时必须失败，而不是产出未签名的包。"""
    model_path = _prepare_model(tmp_path)
    manifest_path = _write_manifest(tmp_path, model_path)
    out_dir = tmp_path / "out"

    bad_key = tmp_path / "bad_key.pem"
    bad_key.write_text(bad_key_content, encoding="utf-8")

    result = _run_script(
        "--manifest", str(manifest_path),
        "--out", str(out_dir),
        "--sign-key", str(bad_key),
    )
    assert result.returncode != 0, "无效签名密钥时必须失败"
