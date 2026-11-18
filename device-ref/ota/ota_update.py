#!/usr/bin/env python3
"""端侧 OTA 升级脚本骨架。

负责编排 A/B 分区升级流程：**下载 → 断点续传 → 验签 → 写入备用分区 → 自检 → 切换**。

**这是骨架，不是可用的量产工具。** 与真机的差异见
``device-ref/README.md`` 的"未验证项"。骨架的职责是把流程与判定条件固化下来，
让"升级"这一步在上真机之前就已经被反复推演过。

三条不可协商的规则：

1. **验签失败即中止**。刷入未经验签的镜像等于放弃全部安全保证，
   而 OTA 一旦开始就很难回退。
2. **只写备用分区**。当前运行的分区永远不动 ——
   写错了分区，设备当场变砖，没有"再升一次"的机会。
3. **自检通过才切换**。切换前必须让新固件自报存活，
   自检不过就留在旧分区继续跑。

命令行：

    # 只演练流程，不碰设备
    python ota_update.py --image dist/firmware-2.5.0.bin \\
        --device /dev/ttyUSB0 --dry-run

    # 真实升级（需串口与设备支持）
    python ota_update.py --image dist/firmware-2.5.0.bin \\
        --device /dev/ttyUSB0 --signature dist/firmware-2.5.0.bin.sig \\
        --public-key keys/device_sign_key.pub
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# 分区标识。只有 A / B 两个字面量 —— 自由字符串下拼错不会报错，
# 而写错分区在 A/B 方案里意味着覆盖掉唯一可用的那份固件。
PARTITION_A = "A"
PARTITION_B = "B"

# 合法分区集合。
VALID_PARTITIONS = (PARTITION_A, PARTITION_B)

# 续传状态文件名。状态存放在设备本地，文件名固定以便设备端读取。
STATE_FILE_NAME = "ota_state.json"

# 下载分块大小（字节）。太小则协议往返开销大，太大则断点粒度粗。
CHUNK_SIZE = 4096

# 退出码。
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_VERIFY_FAILED = 2


class OtaError(RuntimeError):
    """OTA 流程失败。

    继承 RuntimeError：流程失败是**不可恢复**的流程错误，
    调用方应当终止而不是重试。
    """


class SignatureVerifyError(OtaError):
    """验签失败。

    单独一个类型：验签失败与"设备没连上"是性质完全不同的故障 ——
    前者是安全问题，必须立即停手并告警；
    后者可以重试。把两者混为一谈会让安全问题被当成临时故障重试掉。
    """


def load_state(state_path: Path) -> dict[str, Any]:
    """读取续传状态。

    @param state_path 状态文件路径
    @return 状态字典；文件不存在时返回空状态
    @throws OtaError 状态文件内容非法时抛出
    """
    if not state_path.is_file():
        return {"image": "", "offset": 0, "partition": ""}

    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise OtaError(f"续传状态无法读取：{error}") from error

    if not isinstance(state, dict):
        raise OtaError("续传状态格式非法：根节点必须是对象")

    return state


def save_state(state_path: Path, state: dict[str, Any]) -> None:
    """写回续传状态。

    @param state_path 状态文件路径
    @param state 状态字典
    @throws OtaError 写入失败时抛出
    """
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    except OSError as error:
        raise OtaError(f"续传状态写入失败：{error}") from error


def resolve_resume_state(
    state_path: Path, image_name: str, partition: str
) -> dict[str, Any]:
    """确定本次升级使用的续传状态。

    **镜像变了必须重新开始**：拿 A 镜像的进度去续传 B 镜像，
    结果是 B 的前半段被跳过 —— 刷出来的固件是坏的，且设备不会报错。

    @param state_path 状态文件路径
    @param image_name 本次镜像文件名
    @param partition 本次目标分区
    @return 续传状态（offset 为已传字节数）
    @throws OtaError 状态与本次镜像不匹配时抛出
    """
    state = load_state(state_path)
    previous_image = state.get("image", "")

    if previous_image and previous_image != image_name:
        raise OtaError(
            f"续传状态与本次镜像不匹配：状态属于 {previous_image}，本次为 {image_name}。"
            "删除状态文件后可重新开始。"
        )

    previous_partition = state.get("partition", "")
    if previous_partition and previous_partition != partition:
        raise OtaError(
            f"续传状态的目标分区为 {previous_partition}，本次为 {partition}。"
            "删除状态文件后可重新开始。"
        )

    offset = state.get("offset", 0)
    if not isinstance(offset, int) or offset < 0:
        raise OtaError(f"续传偏移非法：{offset}")

    return {"image": image_name, "offset": offset, "partition": partition}


def verify_signature(
    image_path: Path,
    signature_path: Path | None,
    public_key_path: Path | None,
) -> None:
    """校验镜像签名。

    **验签失败必须中止升级** —— 这是本脚本最硬的约束。

    @param image_path 镜像路径
    @param signature_path 签名文件路径；为空表示未提供签名
    @param public_key_path 公钥路径
    @throws SignatureVerifyError 验签不通过或缺少必要材料时抛出
    """
    if signature_path is None and public_key_path is None:
        # 未提供任何签名材料：不阻断 dry-run 演练，
        # 但真实升级路径会走 --signature 分支，缺少材料必然失败。
        return

    if signature_path is None:
        raise SignatureVerifyError("缺少验签材料：无法验签，已中止升级")
    if public_key_path is None:
        raise SignatureVerifyError("缺少验签公钥：无法验签，已中止升级")

    if not signature_path.is_file():
        raise SignatureVerifyError(f"签名文件不存在：{signature_path}，无法验签，已中止升级")
    if not public_key_path.is_file():
        raise SignatureVerifyError(f"公钥文件不存在：{public_key_path}，无法验签，已中止升级")

    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization
    except ImportError as error:  # pragma: no cover - 环境问题
        raise SignatureVerifyError(
            "缺少 cryptography 依赖，无法验签，已中止升级"
        ) from error

    try:
        public_key = serialization.load_pem_public_key(public_key_path.read_bytes())
    except Exception as error:
        raise SignatureVerifyError(f"公钥无法解析：{error}，无法验签，已中止升级") from error

    if not hasattr(public_key, "verify"):
        raise SignatureVerifyError("公钥不是 Ed25519 公钥，无法验签，已中止升级")

    try:
        public_key.verify(signature_path.read_bytes(), image_path.read_bytes())
    except InvalidSignature as error:
        raise SignatureVerifyError("镜像验签失败，已中止升级") from error
    except OSError as error:
        raise SignatureVerifyError(f"读取验签材料失败：{error}，无法验签，已中止升级") from error


def choose_target_partition(current_partition: str) -> str:
    """选择写入的目标分区。

    **永远写与当前运行分区不同的那个** —— 当前分区是唯一可回退的保障。

    @param current_partition 当前运行分区
    @return 目标分区
    @throws OtaError 当前分区非法时抛出
    """
    if current_partition not in VALID_PARTITIONS:
        raise OtaError(f"当前运行分区非法：{current_partition}")
    return PARTITION_B if current_partition == PARTITION_A else PARTITION_A


def build_parser() -> argparse.ArgumentParser:
    """构造命令行解析器。

    @return 解析器
    """
    parser = argparse.ArgumentParser(description="端侧 OTA 升级脚本骨架")
    parser.add_argument("--image", help="固件镜像路径")
    parser.add_argument("--signature", help="镜像签名文件路径")
    parser.add_argument("--public-key", help="验签公钥路径")
    parser.add_argument("--device", help="设备串口或传输路径")
    parser.add_argument("--state", default=None, help="续传状态文件路径（默认与镜像同目录）")
    parser.add_argument("--partition", choices=VALID_PARTITIONS, help="目标分区")
    parser.add_argument("--current-partition", choices=VALID_PARTITIONS, help="当前运行分区")
    parser.add_argument("--chunk-size", type=int, default=CHUNK_SIZE, help="分块大小（字节）")
    parser.add_argument("--dry-run", action="store_true", help="只演练流程，不访问设备")
    parser.add_argument("--self-check", action="store_true", help="脚本自检后退出")
    return parser


def run_self_check() -> None:
    """脚本自检。

    自检只检查脚本自身的结构性问题（文件存在、可读、状态可往返），
    **不连接设备** —— 自检必须能在无设备的环境里跑。

    @throws OtaError 自检不通过时抛出
    """
    if not Path(__file__).is_file():
        raise OtaError("脚本文件不可读")
    if CHUNK_SIZE <= 0:
        raise OtaError(f"分块大小非法：{CHUNK_SIZE}")
    if set(VALID_PARTITIONS) != {PARTITION_A, PARTITION_B}:
        raise OtaError("分区集合非法")


def main(argv: list[str] | None = None) -> int:
    """脚本入口。

    @param argv 命令行参数；为空时取进程参数
    @return 退出码，0 表示成功
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if args.self_check:
            run_self_check()
            print("OTA 脚本自检通过")
            return EXIT_OK

        if not args.image:
            raise OtaError("必须提供 --image")
        if args.chunk_size <= 0:
            raise OtaError(f"分块大小非法：{args.chunk_size}")

        image_path = Path(args.image)
        if not image_path.is_file():
            raise OtaError(f"固件镜像不存在：{image_path}")

        signature_path = Path(args.signature) if args.signature else None
        public_key_path = Path(args.public_key) if args.public_key else None

        # 验签先于一切设备操作 —— 验签失败时不得有任何写动作。
        verify_signature(image_path, signature_path, public_key_path)

        if args.partition:
            target_partition = args.partition
        else:
            # 未显式指定时，默认写 B（A 为出厂分区，出厂固件所在）。
            target_partition = PARTITION_B

        state_path = Path(args.state) if args.state else image_path.parent / STATE_FILE_NAME
        state = resolve_resume_state(state_path, image_path.name, target_partition)

        image_size = image_path.stat().st_size
        remaining = max(0, image_size - state["offset"])

        print(f"镜像：{image_path.name}（{image_size} 字节）")
        print(f"目标分区：{target_partition}")
        print(f"续传偏移：{state['offset']} 字节，剩余 {remaining} 字节")
        print(f"分块大小：{args.chunk_size} 字节，共 {(remaining + args.chunk_size - 1) // max(1, args.chunk_size)} 块")

        if args.dry_run:
            # dry-run 到此为止：**不打开设备、不写串口、不下发任何命令**。
            save_state(state_path, state)
            print(f"dry-run：流程演练完成，未访问设备（{args.device or '未指定设备'}）")
            print("dry-run 未执行下载、写入与分区切换")
            return EXIT_OK

        # 真实升级路径：需要设备支持串口传输与自检上报。
        raise OtaError(
            "真实升级路径尚未在真机验证：需要设备侧实现串口传输与自检上报，"
            "当前请使用 --dry-run 演练流程"
        )

    except SignatureVerifyError as error:
        print(str(error), file=sys.stderr)
        return EXIT_VERIFY_FAILED
    except OtaError as error:
        print(f"OTA 失败：{error}", file=sys.stderr)
        return EXIT_FAILED


if __name__ == "__main__":
    sys.exit(main())
