"""OTA 脚本骨架的行为测试。

OTA 的失败形态是**静默的**：脚本报告"升级成功"而设备实际没更新，
或者脚本把设备刷成砖。两种都极贵。因此本测试盯住三件事：

1. ``--dry-run`` **绝不触碰设备**（不写串口、不发命令）；
2. 断点续传的状态文件格式稳定，且能从中断处继续；
3. 验签失败必须中止，**不得**继续刷写 —— 刷一个没验过的镜像等于放弃所有安全保证。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# 仓库根。测试位于 core/tests/device_ref/，仓库根在其上三层。
REPO_ROOT = Path(__file__).resolve().parents[3]

# OTA 脚本路径。
SCRIPT_PATH = REPO_ROOT / "device-ref" / "ota" / "ota_update.py"

# 状态文件名。续传状态必须放在设备本地，文件名固定以便设备端读取。
STATE_FILE_NAME = "ota_state.json"

# 镜像文件名。
IMAGE_FILE_NAME = "firmware-2.5.0.bin"


def _run_script(*args: str) -> subprocess.CompletedProcess:
    """运行 OTA 脚本。

    **编码**：显式指定 UTF-8 —— Windows 上子进程输出的默认解码是 GBK，
    脚本里的中文错误信息会触发解码异常。

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


def test_script_exists():
    """OTA 脚本必须存在。"""
    assert SCRIPT_PATH.is_file(), f"缺少 OTA 脚本：{SCRIPT_PATH}"


def test_help_lists_dry_run_option():
    """脚本必须支持 --dry-run。

    为什么：没有 dry-run 就无法在不接设备的情况下验证参数与流程编排，
    而"接上设备试一把"是危险得多的验证方式。
    """
    result = _run_script("--help")
    assert result.returncode == 0, f"--help 失败：{result.stderr}"
    assert "--dry-run" in result.stdout


def test_dry_run_does_not_touch_device(tmp_path: Path):
    """--dry-run 不得访问设备。

    为什么：脚本会往串口写命令。dry-run 里若真的写了，
    等于"我以为我在模拟，结果我在刷真机"。

    **如何验证**：脚本接受 --device 指向一个不存在的路径；
    dry-run 成功退出说明它没去打开那个路径（真访问会抛异常）。
    """
    image = tmp_path / IMAGE_FILE_NAME
    image.write_bytes(b"\x00" * 1024)

    result = _run_script(
        "--image", str(image),
        "--device", str(tmp_path / "no-such-device"),
        "--dry-run",
    )
    assert result.returncode == 0, f"dry-run 失败：{result.stderr}"
    assert "dry-run" in result.stdout.lower()


def test_dry_run_reports_target_partition(tmp_path: Path):
    """dry-run 必须报告将写入的分区。

    为什么：A/B 分区方案里"写到哪个分区"是决策的落点 ——
    dry-run 不把它打印出来，dry-run 就没起到复核作用。
    """
    image = tmp_path / IMAGE_FILE_NAME
    image.write_bytes(b"\x00" * 1024)

    result = _run_script(
        "--image", str(image),
        "--device", str(tmp_path / "no-such-device"),
        "--dry-run",
    )
    assert result.returncode == 0
    assert "B" in result.stdout, "dry-run 未报告目标分区"


def test_missing_image_fails(tmp_path: Path):
    """镜像文件不存在时必须失败。"""
    result = _run_script(
        "--image", str(tmp_path / "absent.bin"),
        "--device", str(tmp_path / "no-such-device"),
        "--dry-run",
    )
    assert result.returncode != 0, "镜像缺失时必须失败"


def test_signature_verification_failure_aborts(tmp_path: Path):
    """验签失败必须中止，不得继续刷写。

    为什么：刷入未经验签的镜像等于放弃全部安全保证，
    而 OTA 流程一旦开始就很难回退。

    **如何验证**：用一个内容被篡改的镜像 + 一个只对原始内容有效的签名。
    """
    image = tmp_path / IMAGE_FILE_NAME
    image.write_bytes(b"\x00" * 1024)
    signature = tmp_path / "image.sig"
    # 签名内容与镜像内容无关 —— 必然验签失败。
    signature.write_bytes(b"not-a-valid-signature")

    result = _run_script(
        "--image", str(image),
        "--signature", str(signature),
        "--device", str(tmp_path / "no-such-device"),
        "--dry-run",
    )
    assert result.returncode != 0, "验签失败时必须失败"
    assert "验签" in (result.stdout + result.stderr), "失败原因未指明是验签"


def test_resume_state_file_is_written(tmp_path: Path):
    """续传状态文件必须落盘，且格式可被再次读取。

    为什么：断点续传的状态只在设备本地持久化 ——
    断电后脚本要能读回"已经传到哪了"。状态文件格式不稳定，
    续传会在断电后从头再来（浪费流量）或跳过一段（刷出坏固件）。
    """
    image = tmp_path / IMAGE_FILE_NAME
    image.write_bytes(b"\x00" * 1024)
    state_path = tmp_path / STATE_FILE_NAME

    result = _run_script(
        "--image", str(image),
        "--device", str(tmp_path / "no-such-device"),
        "--state", str(state_path),
        "--dry-run",
    )
    assert result.returncode == 0, f"dry-run 失败：{result.stderr}"
    assert state_path.is_file(), "续传状态文件未落盘"

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["image"] == IMAGE_FILE_NAME
    assert state["offset"] == 0
    assert state["partition"] in ("A", "B")


def test_resume_state_preserves_existing_offset(tmp_path: Path):
    """已有续传进度时不得把偏移重置为 0。

    为什么：重置偏移等于从头再传一遍 ——
    在按流量计费的场景下这是真金白银的损失，在弱网场景下则永远传不完。
    """
    image = tmp_path / IMAGE_FILE_NAME
    image.write_bytes(b"\x00" * 1024)
    state_path = tmp_path / STATE_FILE_NAME
    state_path.write_text(
        json.dumps({"image": IMAGE_FILE_NAME, "offset": 512, "partition": "B"}),
        encoding="utf-8",
    )

    result = _run_script(
        "--image", str(image),
        "--device", str(tmp_path / "no-such-device"),
        "--state", str(state_path),
        "--dry-run",
    )
    assert result.returncode == 0, f"dry-run 失败：{result.stderr}"

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["offset"] == 512, f"续传偏移被重置：{state['offset']}"


def test_resume_state_with_different_image_is_rejected(tmp_path: Path):
    """续传状态与镜像不匹配时必须失败。

    为什么：拿 A 镜像的进度去续传 B 镜像，
    结果是 B 的前半段被跳过 —— 刷出来的固件是坏的，且设备不会报错。
    """
    image = tmp_path / IMAGE_FILE_NAME
    image.write_bytes(b"\x00" * 1024)
    state_path = tmp_path / STATE_FILE_NAME
    state_path.write_text(
        json.dumps({"image": "other-firmware.bin", "offset": 512, "partition": "B"}),
        encoding="utf-8",
    )

    result = _run_script(
        "--image", str(image),
        "--device", str(tmp_path / "no-such-device"),
        "--state", str(state_path),
        "--dry-run",
    )
    assert result.returncode != 0, "镜像与续传状态不匹配时必须失败"


@pytest.mark.parametrize("partition", ["A", "B"])
def test_explicit_partition_is_accepted(tmp_path: Path, partition: str):
    """显式指定分区必须被接受并记录。"""
    image = tmp_path / IMAGE_FILE_NAME
    image.write_bytes(b"\x00" * 1024)
    state_path = tmp_path / STATE_FILE_NAME

    result = _run_script(
        "--image", str(image),
        "--device", str(tmp_path / "no-such-device"),
        "--state", str(state_path),
        "--partition", partition,
        "--dry-run",
    )
    assert result.returncode == 0, f"dry-run 失败：{result.stderr}"

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["partition"] == partition


def test_invalid_partition_is_rejected(tmp_path: Path):
    """非法分区名必须失败。

    为什么：自由字符串下拼错不会报错，而写错分区在 A/B 方案里
    意味着覆盖掉唯一可用的那份固件 —— 设备直接变砖。
    """
    image = tmp_path / IMAGE_FILE_NAME
    image.write_bytes(b"\x00" * 1024)

    result = _run_script(
        "--image", str(image),
        "--device", str(tmp_path / "no-such-device"),
        "--partition", "C",
        "--dry-run",
    )
    assert result.returncode != 0, "非法分区名必须失败"


def test_self_check_mode_passes_on_valid_layout(tmp_path: Path):
    """自检模式在仓库现状下必须通过。

    为什么：自检是"脚本本身没坏"的最低保障 ——
    自检不过还继续刷写，是把脚本缺陷带进设备。
    """
    result = _run_script("--self-check")
    assert result.returncode == 0, f"自检失败：{result.stderr}"
