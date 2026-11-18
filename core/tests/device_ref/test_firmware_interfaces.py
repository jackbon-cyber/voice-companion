"""STM32 固件骨架的接口契约测试。

固件接口是**跨语言契约**：C 侧的常量与函数签名必须与 Python 侧的
`core/edge/` 行为一致，否则换到真机时才暴露"帧长不对""采样率不匹配"。

这里盯住三件事：
1. 头文件齐备且每个端侧任务都有明确的入口函数；
2. 音频格式常量与 `core.edge.audio.negotiation.DEFAULT_FORMAT` 一致；
3. 协议消息字段名与 `core/protocol/schema/` 一致 —— 字段名拼错时，
   编译通过、联调时才发现，是最贵的失败形态。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.edge.audio.negotiation import DEFAULT_FORMAT
from core.protocol.loader import SCHEMA_NAMES, load_schema

# 仓库根。测试位于 core/tests/device_ref/，仓库根在其上三层。
REPO_ROOT = Path(__file__).resolve().parents[3]

# 固件头文件目录。
INCLUDE_DIR = REPO_ROOT / "device-ref" / "firmware" / "include"

# 端侧任务与对应头文件。
# 任务划分依据 OpenSpec tasks.md 11.3：VAD / ASR / 意图 / 状态机。
EXPECTED_TASK_HEADERS: dict[str, str] = {
    "采集与 VAD": "vc_audio_task.h",
    "端侧 ASR": "vc_asr_task.h",
    "意图判定": "vc_intent_task.h",
    "会话状态机": "vc_state_machine.h",
}

# 协议消息与其字段常量名的映射。
# 值是 (固件常量后缀, schema 字段名) 二元组 —— 固件用大写下划线，
# schema 用小驼峰，两者靠这张表对齐。
# 固件不解析 JSON（flash 与实时性都不允许），但常量名必须与 schema 同名，
# 否则联调时"schema 有字段、固件没有"这类差异极难定位。
PROTOCOL_FIELD_CONSTANTS: dict[str, list[tuple[str, str]]] = {
    "audio-frame": [
        ("SESSION_ID", "sessionId"),
        ("SEQUENCE", "sequence"),
        ("TIMESTAMP_MS", "timestampMs"),
        ("PAYLOAD_BASE64", "payloadBase64"),
    ],
    "voice-chunk": [
        ("SESSION_ID", "sessionId"),
        ("SEQUENCE", "sequence"),
        ("IS_FIRST", "isFirst"),
        ("IS_LAST", "isLast"),
    ],
    "text-reply": [
        ("SESSION_ID", "sessionId"),
        ("TEXT", "text"),
    ],
    "session": [
        ("SESSION_ID", "sessionId"),
        ("TYPE", "type"),
    ],
    "intent-report": [
        ("SESSION_ID", "sessionId"),
        ("SEQUENCE", "sequence"),
        ("INTENT", "intent"),
        ("CONFIDENCE", "confidence"),
    ],
    "control-channel": [
        ("SESSION_ID", "sessionId"),
        ("DIRECTION", "direction"),
        ("TYPE", "type"),
    ],
    "degrade-level": [
        ("LEVEL", "level"),
        ("REASON", "reason"),
        ("TIMESTAMP_MS", "timestampMs"),
    ],
}


def _read(name: str) -> str:
    """读取一个头文件的内容。

    @param name 头文件名
    @return 文件文本
    """
    return (INCLUDE_DIR / name).read_text(encoding="utf-8")


def _defines(text: str) -> dict[str, str]:
    """解析头文件里的 `#define` 简单常量。

    只取「单行、以数字或标识符结尾、且不含函数调用」的宏 ——
    含括号的宏是函数式宏，另行处理。

    @param text 头文件文本
    @return 常量名到取值的映射
    """
    pattern = re.compile(r"^#define\s+(\w+)\s+([A-Za-z0-9_\"']+)\s*(?:/\*.*)?$", re.MULTILINE)
    return {name: value for name, value in pattern.findall(text)}


@pytest.mark.parametrize("header_name", sorted(EXPECTED_TASK_HEADERS.values()))
def test_task_header_exists(header_name: str):
    """每个端侧任务都必须有对应的头文件。

    为什么：任务划分是接口的前提；缺头文件意味着该任务的职责边界没定，
    后续实现会在业务代码里临时约定，约定不会同步给云端与端侧两端。
    """
    assert (INCLUDE_DIR / header_name).is_file(), f"缺少固件接口头文件：{header_name}"


@pytest.mark.parametrize("header_name", sorted(EXPECTED_TASK_HEADERS.values()))
def test_task_header_declares_entry_point(header_name: str):
    """每个任务头文件必须声明一个入口函数。

    为什么：RTOS 任务的职责由"谁启动它、它等谁的消息"决定。
    没有入口函数的接口无法在固件里落地，最终会退化成裸循环调用。
    """
    text = _read(header_name)
    assert re.search(r"^[a-zA-Z_][\w \*]*\bvc_\w+_(?:task_)?(?:start|init)\s*\(", text, re.MULTILINE), (
        f"{header_name} 未声明任务入口函数（vc_*_task_start / vc_*_init）"
    )


def test_audio_constants_match_edge_negotiation_defaults():
    """固件的音频格式常量必须与端侧协商默认值一致。

    为什么：固件与 PC 模拟端连的是同一套协议。若固件按 16 kHz 采集、
    模拟端按 8 kHz 协商，两边都"运行正常"，但识别结果全是错的。
    """
    text = _read("vc_audio_task.h")
    defines = _defines(text)

    assert int(defines["VC_AUDIO_SAMPLE_RATE_HZ"]) == DEFAULT_FORMAT.sample_rate
    assert int(defines["VC_AUDIO_CHANNELS"]) == DEFAULT_FORMAT.channels
    assert int(defines["VC_AUDIO_BITS_PER_SAMPLE"]) == DEFAULT_FORMAT.bit_depth

    # 帧长必须与采样率自洽，否则时间戳会漂移。
    frame_ms = int(defines["VC_AUDIO_FRAME_DURATION_MS"])
    frame_samples = int(defines["VC_AUDIO_FRAME_SAMPLES"])
    expected_samples = DEFAULT_FORMAT.sample_rate * frame_ms // 1000
    assert frame_samples == expected_samples, (
        f"帧长与采样率不自洽：{frame_samples} != {expected_samples}"
    )


@pytest.mark.parametrize("schema_name", sorted(PROTOCOL_FIELD_CONSTANTS))
def test_protocol_field_constants_exist(schema_name: str):
    """协议字段必须���固件侧有同名常量。

    为什么：固件不解析 JSON，但常量名必须与 schema 字段名对齐 ——
    对齐后，"schema 改了字段"可以靠本测试立刻发现。
    """
    text = _read("vc_protocol.h")
    defines = _defines(text)

    for constant_suffix, _schema_field in PROTOCOL_FIELD_CONSTANTS[schema_name]:
        constant_name = f"VC_{constant_suffix}"
        assert constant_name in defines, f"固件缺少协议字段常量：{constant_name}"


@pytest.mark.parametrize("schema_name", sorted(SCHEMA_NAMES))
def test_every_protocol_schema_has_a_firmware_section(schema_name: str):
    """每份协议 schema 在固件侧都要有对应段落。

    为什么：协议新增消息类型时，固件必须同步决定"收不收、怎么处理"。
    没有段落意味着固件会把它当未知消息丢弃，而丢弃不会报错。
    """
    text = _read("vc_protocol.h")
    assert schema_name in text, f"固件协议头未覆盖消息类型：{schema_name}"


def test_unknown_message_is_rejected_not_ignored():
    """未知消息类型必须显式拒绝。

    为什么：静默忽略未知消息会让"新协议在旧固件上不生效"这件事
    完全不可见 —— 用户只看到"设备不响应了"。
    """
    text = _read("vc_protocol.h")
    assert re.search(r"VC_PROTOCOL_(?:UNKNOWN|REJECT)", text), (
        "固件协议头未定义未知消息的处理方式"
    )


def test_state_machine_declares_all_six_states():
    """会话状态机必须声明六态。

    为什么：六态（IDLE/LISTENING/THINKING/WAITING_CLOUD/SPEAKING/INTERRUPTED）
    是端侧行为的核心契约；少一个态会让降级与打断的处理出现真空地带。
    """
    text = _read("vc_state_machine.h")
    for state in ("IDLE", "LISTENING", "THINKING", "WAITING_CLOUD", "SPEAKING", "INTERRUPTED"):
        assert f"VC_STATE_{state}" in text, f"状态机缺少状态：{state}"


def test_state_machine_states_match_edge_implementation():
    """固件声明的状态必须与端侧实现的状态集合一致。

    为什么：两端状态机不一致时，固件会在 Python 侧不存在的状态上卡住 ——
    例如固件有 DEGRADED 而 Python 没有，云端降级指令下发后端侧状态机
    收不到该状态，行为随实现而异，最难复现。
    """
    from core.edge.session.state_machine import SessionState

    text = _read("vc_state_machine.h")
    # 只取定义为整数的状态常量 —— 避免把同前缀的宏（如超时阈值）算作状态。
    firmware_states = {
        name[len("VC_STATE_") :]
        for name, value in _defines(text).items()
        if name.startswith("VC_STATE_") and value.isdigit() and name != "VC_STATE_TOTAL"
    }
    python_states = {state.value for state in SessionState}
    assert firmware_states == python_states, (
        f"固件状态集合 {sorted(firmware_states)} 与端侧实现 {sorted(python_states)} 不一致"
    )


def test_schema_field_names_are_camel_case_constants():
    """schema 字段名本身必须是合法的常量名候选。

    为什么：这是"schema 与固件常量对应"的前提。字段名含非法字符时，
    固件侧只能手写映射，一一对应关系会随字段增多而失守。
    """
    for schema_name in PROTOCOL_FIELD_CONSTANTS:
        schema = load_schema(schema_name)
        for _constant_suffix, schema_field in PROTOCOL_FIELD_CONSTANTS[schema_name]:
            assert schema_field in schema["properties"], (
                f"{schema_name} 的 schema 中没有字段 {schema_field}"
            )
