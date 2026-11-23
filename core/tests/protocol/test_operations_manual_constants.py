"""操作手册里引用的固件常量必须真实存在，且不漏字段。

**这个测试回答什么问题**

"设备实现者照抄手册里的常量名，能编译过吗？"

`docs/operations-manual.md` 给设备实现者列了 `VC_*` 常量名和
"字段名 → 常量"的对照表。手册写错一个常量名，设备照抄就编译不过；
漏掉一个字段常量，设备实现者按"用常量、别手写字面量"的指引做，
却找不到可用的常量。

早先就出过一次：`ownerKey` 在固件里**没有**对应常量，
而它是跨用户隔离的根基。手册还写成了不存在的 `VC_FIELD_SESSION_ID`。

**怎么检查**

1. 手册里出现的每个 `VC_*` 常量，必须在固件某个头文件里 `#define` 过；
2. 每个协议字段都必须有常量，且手册里要有它的条目。
   固件侧刻意不提供的字段（如 `slots`）走显式例外清单。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.protocol.loader import SCHEMA_NAMES, load_schema

REPO_ROOT = Path(__file__).resolve().parents[3]
INCLUDE_DIR = REPO_ROOT / "device-ref" / "firmware" / "include"
MANUAL_PATH = REPO_ROOT / "docs" / "operations-manual.md"

# 固件侧刻意不提供常量的字段。理由见 device-ref 的 README 与
# core/tests/device_ref/test_firmware_interfaces.py 的 EXCLUDED_CONSTANTS。
FIELDMAP_EXEMPTIONS: dict[str, set[str]] = {
    "intent-report": {"slots"},
}


def _all_firmware_constants() -> set[str]:
    """收集固件全部头文件里定义的 VC_ 常量。

    @return: 常量名集合
    """
    constants: set[str] = set()
    for header in INCLUDE_DIR.glob("*.h"):
        constants |= set(
            re.findall(r"#define\s+(VC_[A-Z0-9_]+)", header.read_text(encoding="utf-8"))
        )
    return constants


def _camel_to_constant_suffix(field: str) -> str:
    """字段名转常量后缀。

    @param field 小驼峰字段名
    @return: 全大写下划线后缀
    """
    return re.sub(r"(?<!^)(?=[A-Z])", "_", field).upper()


@pytest.fixture(scope="module")
def manual_text() -> str:
    """读手册全文。

    @return: 手册文本
    """
    return MANUAL_PATH.read_text(encoding="utf-8")


def test_manual_exists():
    """手册必须在 —— 不然下面两条检查就没有对象。

    为什么：手册是这个仓库里唯一的设备接入依据，
    删掉它等于让设备实现者无路可走。
    """
    assert MANUAL_PATH.is_file(), f"操作手册不存在：{MANUAL_PATH}"


def test_every_constant_mentioned_in_manual_exists(manual_text: str):
    """手册提到的每个 VC_ 常量都必须在固件里真实存在。

    为什么：设备实现者照抄常量名去写固件。
    手册写了不存在的常量名，设备侧**编译不过**，
    而排查方向会指向"固件环境不对"，真因在文档。
    """
    firmware_constants = _all_firmware_constants()
    mentioned = set(re.findall(r"VC_[A-Z0-9_]+", manual_text))

    missing = sorted(mentioned - firmware_constants)

    assert not missing, (
        f"操作手册引用了固件里不存在的常量：{missing}\n"
        f"请修正 docs/operations-manual.md，或在固件里补上这些常量。"
    )


def test_every_protocol_field_is_documented_in_manual(manual_text: str):
    """每个协议字段都要在手册里有对应条目。

    为什么：手册第 1.2 节说"用常量，别手写字符串字面量"。
    字段没有常量时，设备实现者只能手写字面量 ——
    正好违反手册自己的指引。
    """
    undocumented: list[str] = []

    for schema_name in SCHEMA_NAMES:
        exemptions = FIELDMAP_EXEMPTIONS.get(schema_name, set())
        for field in load_schema(schema_name)["properties"]:
            if field in exemptions:
                continue
            constant = f"VC_{_camel_to_constant_suffix(field)}"
            if constant not in manual_text:
                undocumented.append(f"{schema_name}.{field} → {constant}")

    assert not undocumented, (
        f"这些协议字段在操作手册里没有对应条目：{undocumented}\n"
        f"请补进 docs/operations-manual.md 的附录 A.2。"
    )


def test_manual_does_not_use_the_wrong_prefix(manual_text: str):
    """手册不得出现 VC_FIELD_ 前缀（早先写错成 VC_FIELD_SESSION_ID）。

    为什么：固件的常量命名是 VC_ + 字段名转大写下划线，没有 FIELD 这一层。
    写成 VC_FIELD_SESSION_ID 会让设备实现者以为有层级，
    找不到就自己定义一个，行为就分叉了。
    """
    wrong = sorted(set(re.findall(r"VC_FIELD_[A-Z0-9_]+", manual_text)))

    assert not wrong, (
        f"操作手册出现了不存在的常量前缀：{wrong}\n"
        f"固件常量没有 FIELD 这一层，正确形式是 VC_SESSION_ID。"
    )


def test_manual_and_firmware_agree_on_the_owner_key_constant(manual_text: str):
    """ownerKey 必须有固件常量，且手册里有它 —— 跨用户隔离的根基。

    为什么：ownerKey 缺失时云端记忆全部落进默认作用域，
    跨用户隔离失效，而**功能不报错**。
    这个常量缺失过一次，代价是设备实现者无路可走。
    """
    firmware_constants = _all_firmware_constants()

    assert "VC_OWNER_KEY" in firmware_constants, (
        "固件缺少 VC_OWNER_KEY 常量 —— ownerKey 是跨用户隔离的根基，"
        "设备实现者按手册指引找不到常量时只能手写字面量。"
    )
    assert "VC_OWNER_KEY" in manual_text, "操作手册未提到 VC_OWNER_KEY"
