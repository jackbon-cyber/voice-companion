#!/usr/bin/env python3
"""端侧模型包打包脚本。

把一份模型清单与它引用的模型文件打包成一个可分发的模型包目录：
计算每个模型的 sha256、校验清单合法性、复制模型文件、生成签名。

**打包产物是目录而不是单一容器文件** —— 理由见同目录 README 的
"与技术架构方案 §4.6 的偏离"一节。

命令行：

    # 生成签名密钥（只需一次；私钥不得入库）
    python package_model.py --gen-key keys/device_sign_key.pem

    # 打包
    python package_model.py --manifest build/manifest.json \\
        --out dist/companion_model_pkg --sign-key keys/device_sign_key.pem
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any

# 清单 schema 路径。
SCHEMA_PATH = Path(__file__).resolve().parent / "manifest.schema.json"

# 包内模型目录名。与 manifest.schema.json 的 file pattern 保持一致。
MODELS_DIR_NAME = "models"

# 包内签名文件名。
SIGNATURE_FILE_NAME = "signature.sig"

# 清单内的签名文件名。与 manifest.schema.json 的 signatureFile 保持一致。
MANIFEST_SIGNATURE_FILE_NAME = "signature.sig"

# 打包失败时的退出码。
EXIT_FAILED = 1


class PackagingError(RuntimeError):
    """打包失败。

    继承 RuntimeException：打包失败是**不可恢复**的流程错误，
    调用方应当终止而不是重试。
    """


def load_schema() -> dict:
    """加载清单 schema。

    @return schema 字典
    """
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def compute_sha256(file_path: Path) -> str:
    """计算文件的 sha256。

    @param file_path 文件路径
    @return 64 位十六进制小写摘要
    @throws PackagingError 文件不存在时抛出
    """
    if not file_path.is_file():
        raise PackagingError(f"模型文件不存在：{file_path}")
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_version(version: str) -> tuple[int, int, int]:
    """把三段式版本号解析为可比较的元组。

    @param version 版本号文本
    @return (主, 次, 修订)
    @throws PackagingError 版本号格式非法时抛出
    """
    parts = version.split(".")
    if len(parts) != 3:
        raise PackagingError(f"版本号必须为三段式：{version}")
    try:
        return tuple(int(part) for part in parts)  # type: ignore[return-value]
    except ValueError as error:
        raise PackagingError(f"版本号含非数字段：{version}") from error


def validate_manifest(manifest: dict, schema: dict) -> None:
    """校验清单的合法性与语义不变量。

    分两层：
    1. **schema 层** —— 结构、必填项、取值范围；
    2. **语义层** —— schema 表达不了的约束（当前只有固件版本区间的先后）。

    @param manifest 清单
    @param schema 清单 schema
    @throws PackagingError 校验不通过时抛出
    """
    try:
        from jsonschema import Draft202012Validator
    except ImportError as error:  # pragma: no cover - 环境问题
        raise PackagingError("缺少 jsonschema 依赖，无法校验清单") from error

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(manifest), key=lambda item: list(item.absolute_path))
    if errors:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error.absolute_path) or '(根)'}：{error.message}"
            for error in errors
        )
        raise PackagingError(f"清单不符合 schema：{details}")

    validate_firmware_range(manifest)


def validate_firmware_range(manifest: dict) -> None:
    """校验固件兼容区间的先后顺序。

    **为什么由脚本而非 schema 承担**：JSON Schema Draft 2020-12 没有跨字段的
    语义化版本比较能力；用 pattern 近似会在带预发布标识的版本号上出错，
    比不校验更糟。

    @param manifest 清单
    @throws PackagingError 区间颠倒时抛出
    """
    compat = manifest.get("compat", {})
    firmware_min = compat.get("firmwareMin")
    firmware_max = compat.get("firmwareMax")
    if firmware_min is None or firmware_max is None:
        raise PackagingError("清单缺少固件兼容区间")

    if parse_version(firmware_min) > parse_version(firmware_max):
        raise PackagingError(
            f"固件兼容区间颠倒：firmwareMin={firmware_min} 大于 firmwareMax={firmware_max}"
        )


def resolve_model_path(manifest_dir: Path, relative_path: str) -> Path:
    """把清单中的相对路径解析为实际文件路径。

    **拒绝路径穿越**：清单里的 `file` 若能指向包外的文件，
    打包就会把任意文件复制进产物 —— 产物内容不再由清单决定。

    @param manifest_dir 清单所在目录
    @param relative_path 清单中的相对路径
    @return 模型文件的绝对路径
    @throws PackagingError 路径越界或文件不存在时抛出
    """
    candidate = (manifest_dir / relative_path).resolve()
    base = manifest_dir.resolve()
    if not candidate.is_relative_to(base):
        raise PackagingError(f"模型路径越界：{relative_path}")
    if not candidate.is_file():
        raise PackagingError(f"模型文件不存在：{candidate}")
    return candidate


def load_signing_key(key_path: Path):
    """加载签名私钥。

    @param key_path 私钥路径
    @return Ed25519 私钥对象
    @throws PackagingError 依赖缺失或密钥不可读时抛出
    """
    try:
        from cryptography.hazmat.primitives import serialization
    except ImportError as error:
        raise PackagingError(
            "缺少 cryptography 依赖，无法签名。用 pip install cryptography 安装。"
        ) from error

    if not key_path.is_file():
        raise PackagingError(f"签名密钥不存在：{key_path}")
    try:
        private_key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    except Exception as error:
        raise PackagingError(f"签名密钥无法解析：{error}") from error
    if not hasattr(private_key, "sign"):
        raise PackagingError("签名密钥不是 Ed25519 私钥")
    return private_key


def sign_bytes(private_key, payload: bytes) -> bytes:
    """对负载签名。

    @param private_key Ed25519 私钥
    @param payload 待签名内容
    @return 签名字节
    """
    return private_key.sign(payload)


def generate_key(key_path: Path) -> None:
    """生成一份 Ed25519 签名私钥。

    @param key_path 输出路径
    @throws PackagingError 生成失败时抛出
    """
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError as error:
        raise PackagingError(
            "缺少 cryptography 依赖，无法生成密钥。用 pip install cryptography 安装。"
        ) from error

    key_path.parent.mkdir(parents=True, exist_ok=True)
    private_key = Ed25519PrivateKey.generate()
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    key_path.write_bytes(pem)


def build_package(manifest_path: Path, out_dir: Path, sign_key_path: Path) -> dict:
    """执行打包。

    @param manifest_path 清单路径
    @param out_dir 产物目录
    @param sign_key_path 签名私钥路径
    @return 产出清单
    @throws PackagingError 打包过程中任一环节失败时抛出
    """
    if not manifest_path.is_file():
        raise PackagingError(f"清单不存在：{manifest_path}")

    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    schema = load_schema()
    validate_manifest(manifest, schema)

    manifest_dir = manifest_path.parent
    models = manifest.get("models", [])

    # 先把每个模型的真实 sha256 写回清单 —— 清单里的值必须反映实际内容。
    enriched_models = []
    for model in models:
        relative_path = model.get("file", "")
        model_path = resolve_model_path(manifest_dir, relative_path)
        actual_sha256 = compute_sha256(model_path)
        actual_size = model_path.stat().st_size
        enriched = dict(model)
        enriched["sha256"] = actual_sha256
        enriched["size"] = actual_size
        enriched_models.append(enriched)

    enriched_manifest = dict(manifest)
    enriched_manifest["models"] = enriched_models
    enriched_manifest["signatureAlgorithm"] = "Ed25519"
    enriched_manifest["signatureFile"] = MANIFEST_SIGNATURE_FILE_NAME

    # 二次校验：写回 sha256 之后清单仍必须合法。
    validate_manifest(enriched_manifest, schema)

    private_key = load_signing_key(sign_key_path)

    out_dir.mkdir(parents=True, exist_ok=True)
    models_out = out_dir / MODELS_DIR_NAME
    models_out.mkdir(parents=True, exist_ok=True)

    for model in enriched_models:
        source = resolve_model_path(manifest_dir, model["file"])
        target = models_out / Path(model["file"]).name
        shutil.copyfile(source, target)

    manifest_bytes = json.dumps(enriched_manifest, ensure_ascii=False, indent=2, sort_keys=True).encode(
        "utf-8"
    )
    (out_dir / "manifest.json").write_bytes(manifest_bytes)
    (out_dir / SIGNATURE_FILE_NAME).write_bytes(sign_bytes(private_key, manifest_bytes))

    return enriched_manifest


def build_parser() -> argparse.ArgumentParser:
    """构造命令行解析器。

    @return 解析器
    """
    parser = argparse.ArgumentParser(description="端侧模型包打包脚本")
    parser.add_argument("--manifest", help="清单文件路径")
    parser.add_argument("--out", help="产物目录")
    parser.add_argument("--sign-key", help="签名私钥路径")
    parser.add_argument("--gen-key", help="生成签名私钥到该路径后退出")
    return parser


def main(argv: list[str] | None = None) -> int:
    """脚本入口。

    @param argv 命令行参数；为空时取进程参数
    @return 退出码，0 表示成功
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.gen_key:
            generate_key(Path(args.gen_key))
            print(f"签名私钥已生成：{args.gen_key}")
            return 0

        if not args.manifest or not args.out:
            raise PackagingError("必须提供 --manifest 与 --out")
        if not args.sign_key:
            # 未签名的包等于明文分发的模型文件：攻击者可替换模型而设备端无从察觉。
            raise PackagingError("必须提供 --sign-key：未签名的模型包不得分发")

        manifest = build_package(
            Path(args.manifest), Path(args.out), Path(args.sign_key)
        )
        print(f"模型包已产出：{args.out}")
        print(f"包内模型 {len(manifest['models'])} 个，平台 {manifest['platform']}")
        return 0
    except PackagingError as error:
        print(f"打包失败：{error}", file=sys.stderr)
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
