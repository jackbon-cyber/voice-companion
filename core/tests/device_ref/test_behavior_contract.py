"""端侧行为契约的核对测试。

**这个测试回答什么问题**

"固件和 PC 模拟端的行为是否一致？"

现有 `test_firmware_interfaces.py` 守的是**结构**（常量在不在、字段名拼没拼错、
状态集合一不一致）。但结构一致**不等于**行为一致 —— 固件头文件里写着的
语义承诺，和 PC 侧实际跑出来的行为，可能对不上。

这个测试把 `core.edge.device_ref.behavior_contract` 里的契约清单逐条核对：
1. 固件侧声明的常量，PC 侧必须有对应且**取值一致**；
2. 固件侧声明的符号，PC 侧**不能没有对应**（漏实现是最难发现的一类）；
3. 行为规则类契约，用**实际执行**验证，不只是比对符号名。

**为什么行为规则要真的跑一遍**

比对符号名只能证明"两边都有这个函数"，证明不了"两边行为一样"。
比如"打断丢音频、留文本" —— 固件声明了 `on_recognized`，
PC 侧也有 `on_recognized`，但 PC 侧如果只记长度不记内容，
打断时 `retained_text` 就是空的。**只有真的打断一次才知道**。

**这个测试验不了什么**

延迟绝对值、栈深度、功耗、I2S 时序 —— 必须在真机上测。
这些项在 `HARDWARE_ONLY_MEASUREMENTS` 里明确列出，
本测试断言它们**存在且写明了验证方式**，
但不对它们做任何数值断言。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.edge.device_ref.behavior_contract import (
    BEHAVIOR_CONTRACTS,
    HARDWARE_ONLY_MEASUREMENTS,
    BehaviorContract,
    ContractKind,
    contract_by_id,
)

# 仓库根。测试位于 core/tests/device_ref/，仓库根在其上三层。
REPO_ROOT = Path(__file__).resolve().parents[3]

# 固件头文件目录。
INCLUDE_DIR = REPO_ROOT / "device-ref" / "firmware" / "include"


def _read(header_name: str) -> str:
    """读取一个头文件的内容。

    @param header_name 头文件名
    @return 文件文本
    """
    return (INCLUDE_DIR / header_name).read_text(encoding="utf-8")


def _defines(text: str) -> dict[str, str]:
    """解析头文件里的 `#define` 简单常量。

    @param text 头文件文本
    @return 常量名到取值的映射
    """
    pattern = re.compile(
        r"^#define\s+(\w+)\s+([A-Za-z0-9_\"']+)\s*(?:/\*.*)?$", re.MULTILINE
    )
    return {name: value for name, value in pattern.findall(text)}


def _resolve_python_value(symbol: str):
    """按 `模块::属性` 的形式解析 PC 侧符号的值。

    用双冒号分隔：模块名本身含点（`core.edge.audio.vad`），
    用单冒号会让正则无法判断模块名的边界 —— 实测把
    `core.edge.audio.negotiation::DEFAULT_FORMAT.sample_rate`
    误解析成模块 `core.edge.audio` + 属性 `negotiation::...`。

    支持三种写法：
    - `模块::常量名` —— 直接取模块级常量；
    - `模块::类名.属性名` —— 取类的类属性；
    - `模块::1000（说明）` —— 说明性文字，取括号前的数字。

    @param symbol 符号描述
    @return 解析出的值
    """
    import importlib

    match = re.match(r"^([\w.]+)::(.+)$", symbol)
    assert match, (
        f"无法解析 PC 侧符号描述：{symbol}"
        f"（格式应为 `模块::属性`，模块名含点，必须用双冒号分隔）"
    )
    module_name, attribute_path = match.groups()

    module = importlib.import_module(module_name)

    # 说明性写法："1000（PC 侧用 0~1 浮点，比例相同）"。
    explanation = re.match(r"^(\d+)（", attribute_path)
    if explanation:
        return int(explanation.group(1))

    current = module
    for part in attribute_path.split("."):
        current = getattr(current, part)
    return current


# ----------------------------------------------------------------------
# 契约清单本身的完整性
# ----------------------------------------------------------------------


def test_contract_ids_are_unique():
    """契约标识必须唯一。

    为什么：标识是报告与定位问题的锚点。重复的标识会让"这条契约违反了"
    指向不唯一，排查时无法定位到具体是哪一条。
    """
    identifiers = [item.contract_id for item in BEHAVIOR_CONTRACTS]
    assert len(identifiers) == len(set(identifiers)), (
        f"契约标识重复：{[i for i in identifiers if identifiers.count(i) > 1]}"
    )


def test_every_contract_documents_why():
    """每条契约都必须写明"不做会怎样"。

    为什么：没有理由的契约会在下次重构时被当成"多余的限制"删掉。
    理由是这个清单能存活下来的唯一保障。
    """
    for item in BEHAVIOR_CONTRACTS:
        assert len(item.rationale) >= 10, (
            f"契约 {item.contract_id} 的理由过短或缺失"
        )


def test_contract_covers_all_firmware_headers():
    """每个固件头文件都必须至少被一条契约覆盖。

    为什么：新加一个固件头文件却没进契约清单，意味着它的行为
    **没有任何东西守着** —— 真机上的行为与 PC 侧不一致时不会有人发现。
    """
    covered = {item.firmware_header for item in BEHAVIOR_CONTRACTS}
    headers = {path.name for path in INCLUDE_DIR.glob("*.h")}

    # vc_protocol.h 只声明字段名与消息段，行为由协议 schema 与云端决定，
    # 不构成"端侧行为"，因此不要求行为契约。
    headers.discard("vc_protocol.h")

    missing = headers - covered
    assert not missing, (
        f"这些固件头文件没有任何行为契约覆盖：{sorted(missing)}"
    )


def test_hardware_only_items_state_how_to_measure():
    """真机专属项必须写明"真机上怎么测"。

    为什么：写不出验证方式的条目不是"待验证项"，
    而是想不清楚的条目。列在清单里只会给人"这件事有人跟进了"的错觉。
    """
    for identifier, description, method in HARDWARE_ONLY_MEASUREMENTS:
        assert identifier.strip(), "真机专属项缺少标识"
        assert len(description) >= 4, f"真机专属项 {identifier} 缺少描述"
        assert len(method) >= 10, (
            f"真机专属项 {identifier} 没写明验证方式"
        )


def test_hardware_only_items_do_not_overlap_with_contracts():
    """真机专属项不能与 PC 侧契约重复。

    为什么：同一件事既在 PC 侧断言、又在真机专属清单里，
    说明边界没划清 —— 读者会困惑"这个到底该在哪里验"。
    """
    contract_ids = {item.contract_id for item in BEHAVIOR_CONTRACTS}
    hardware_ids = {identifier for identifier, _, _ in HARDWARE_ONLY_MEASUREMENTS}
    overlap = contract_ids & hardware_ids
    assert not overlap, f"以下项同时出现在两侧：{sorted(overlap)}"


# ----------------------------------------------------------------------
# 数值常量类契约
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "contract",
    [item for item in BEHAVIOR_CONTRACTS if item.kind is ContractKind.NUMERIC_CONSTANT],
    ids=lambda item: item.contract_id,
)
def test_numeric_constant_matches(contract: BehaviorContract):
    """固件侧常量值必须与 PC 侧参考实现一致。

    为什么：这类不一致是"两边都运行正常、结果全错"的典型来源。
    采样率、帧长、阈值差一点，肉眼完全看不出来。
    """
    text = _read(contract.firmware_header)
    defines = _defines(text)

    assert contract.firmware_symbol in defines, (
        f"固件 {contract.firmware_header} 缺少常量 {contract.firmware_symbol}"
    )

    firmware_value = defines[contract.firmware_symbol]
    python_value = _resolve_python_value(contract.python_symbol)

    # 固件侧常量的单位可能与 PC 侧不同（千分比 vs 归一化比值），
    # 因此不直接比数值，而是比"换算到同一单位"后的值。
    #
    # 换算系数由契约自己声明 —— 不在这里猜，猜错会让测试变成恒真。
    scale = _firmware_scale(contract)

    # 自洽类契约：固件的帧采样点数必须等于「采样率 × 帧长 ÷ 1000」。
    # 这类契约比的是**关系**而不是某个常量值。
    if contract.contract_id == "audio.frame_samples":
        sample_rate = int(defines["VC_AUDIO_SAMPLE_RATE_HZ"])
        frame_ms = int(defines["VC_AUDIO_FRAME_DURATION_MS"])
        expected = sample_rate * frame_ms // 1000
        assert int(firmware_value) == expected, (
            f"{contract.contract_id}：固件 {contract.firmware_symbol}={firmware_value}，"
            f"但 {sample_rate}Hz × {frame_ms}ms 应为 {expected} 个采样点"
        )
        return

    assert float(firmware_value) * scale == pytest.approx(float(python_value)), (
        f"{contract.contract_id}：固件 {contract.firmware_symbol}={firmware_value}"
        f"（换算系数 {scale}）与 PC 侧 {contract.python_symbol}={python_value} 不一致"
    )


def _firmware_scale(contract: BehaviorContract) -> float:
    """返回固件常量到 PC 侧单位的换算系数。

    只有两类需要换算：
    - 固件用千分比（0.6 → 600）、PC 侧用归一化比值；
    - 固件与 PC 侧单位相同（系数 1）。

    换算系数**按契约硬编码**，不从代码里推导 ——
    从代码推导会让"代码改了、契约跟着改"，测试变成恒真。
    """
    scales = {
        "vad.speech_probability_threshold": 1 / 1000,
        "vad.energy_threshold": 1 / 1000,
        "intent.keyword_only_threshold": 1 / 1000,
        "intent.confidence_scale": 1,
    }
    return scales.get(contract.contract_id, 1.0)


# ----------------------------------------------------------------------
# 枚举集合类契约
# ----------------------------------------------------------------------


def test_state_set_matches():
    """固件声明的状态集合必须与 PC 侧完全相同。

    为什么：少一个态会让降级与打断的处理出现真空地带；
    多一个态则固件会停在 PC 侧不存在的状态上。
    """
    from core.edge.session.state_machine import SessionState

    text = _read("vc_state_machine.h")
    firmware_states = {
        name[len("VC_STATE_") :]
        for name, value in _defines(text).items()
        if name.startswith("VC_STATE_") and value.isdigit() and name != "VC_STATE_TOTAL"
    }
    python_states = {state.value for state in SessionState}

    assert firmware_states == python_states, (
        f"固件状态集合 {sorted(firmware_states)} 与 PC 侧 {sorted(python_states)} 不一致"
    )


# ----------------------------------------------------------------------
# 行为规则类契约：真的跑一遍
# ----------------------------------------------------------------------


def test_barge_in_keeps_recognized_text():
    """打断必须保留已识别的文本内容（而不只是长度）。

    为什么：这是陪伴场景最不能接受的失败形态 ——
    用户说"等等"，机器人连同前面那句一起不说了。
    """
    from core.edge.session.state_machine import SessionStateMachine

    machine = SessionStateMachine()
    machine.on_recognized("我妈妈叫李芳")
    machine.on_playback_queued(6400)
    machine.on_playback_started(0)

    event = machine.on_user_speech_start(100)

    assert event is not None, "机器人说话时用户开口应当是一次打断"
    assert event.retained_text == "我妈妈叫李芳", (
        f"打断后丢失了已识别的文本，实际保留：{event.retained_text!r}"
    )
    assert event.discarded_audio_bytes == 6400, "打断必须丢弃尚未播出的音频"


def test_barge_in_event_exposes_text_length_for_firmware_parity():
    """打断事件必须暴露已保留文本的长度。

    为什么：固件侧 `vc_barge_in_event_t` 用 `retained_text_length`（uint16）
    表达"保留了多少文本"。PC 侧只给内容不给长度时，
    固件实现者只能自行猜测该填什么 —— 这正是行为分歧的来源。
    """
    from core.edge.session.state_machine import SessionStateMachine

    machine = SessionStateMachine()
    machine.on_recognized("我妈妈叫李芳")
    machine.on_playback_started(0)

    event = machine.on_user_speech_start(100)

    assert event is not None
    assert hasattr(event, "retained_text_length"), (
        "打断事件缺少 retained_text_length，"
        "与固件 vc_barge_in_event_t 的 retained_text_length 无法对齐"
    )
    assert event.retained_text_length == len(event.retained_text.encode("utf-8")), (
        "retained_text_length 必须是 UTF-8 字节长度"
    )


def test_timeout_returns_to_idle_from_every_state():
    """任何非 IDLE 状态超时后都必须回到 IDLE。

    为什么：卡在 WAITING_CLOUD 意味着麦克风再也不听了 ——
    用户说什么都没反应。这是最危险的超时。
    """
    from core.edge.session.state_machine import SessionState, SessionStateMachine

    def machine_in(state: SessionState) -> SessionStateMachine:
        """构造一个处于指定状态的状态机。"""
        machine = SessionStateMachine()
        if state is SessionState.IDLE:
            return machine
        if state is SessionState.LISTENING:
            machine.on_user_speech_start(0)
        elif state is SessionState.THINKING:
            machine.on_user_speech_start(0)
            machine.on_local_processing_started(0)
        elif state is SessionState.WAITING_CLOUD:
            machine.on_user_speech_start(0)
            machine.on_local_processing_started(0)
            machine.on_cloud_wait_started(0)
        elif state is SessionState.SPEAKING:
            machine.on_playback_started(0)
        elif state is SessionState.INTERRUPTED:
            machine.on_playback_started(0)
            machine.on_user_speech_start(0)
        return machine

    for state in SessionState:
        machine = machine_in(state)
        if state is SessionState.IDLE:
            assert machine.on_timeout(60_000) is None, "IDLE 状态不应触发超时转移"
            continue

        transition = machine.on_timeout(60_000)
        assert transition is not None, f"{state.value} 超时未触发转移"
        assert transition.current is SessionState.IDLE, (
            f"{state.value} 超时后应回到 IDLE，实际到了 {transition.current.value}"
        )


def test_local_intent_handling_is_limited_to_fixed_commands():
    """端侧本地执行的意图必须是可逆的固定指令。

    为什么：不可逆操作（支付、删除）放在端侧没有回滚机会；
    端侧判错意图会让机器人做出完全不相干的回应。
    """
    from core.edge.intent.detector import IntentDetector
    from core.edge.intent.rules import DEFAULT_RULES

    # 规则表里出现的每个意图都必须是"可逆的低风险固定指令"。
    # 名单是显式的 —— 不靠关键词黑名单兜底，
    # 因为黑名单永远漏（"取消订单"不在黑名单里，但同样是不可逆的）。
    reversible_local_intents = {
        "set_volume",
        "stop_speaking",
        "play_music",
        "check_time",
        "weather_query",
        "check_device_status",
    }

    declared = {rule.intent for rule in DEFAULT_RULES}
    unexpected = declared - reversible_local_intents
    assert not unexpected, (
        f"这些意图被放在端侧本地执行，但不在可逆低风险名单内：{sorted(unexpected)}"
    )

    detector = IntentDetector()
    decision = detector.detect("声音大一点", 0.95)
    assert decision.handled_locally is True
    assert decision.intent == "set_volume"


def test_turn_change_discards_collected_frames():
    """换人必须丢弃已收集的音频。

    为什么：把换人当成句末送出去，机器人会把别人的话当成用户说的复述一遍。
    """
    from core.edge.audio.sentence import (
        DEFAULT_TURN_SILENCE_MS,
        EVENT_TURN_CHANGE,
        SentenceSegmenter,
    )

    segmenter = SentenceSegmenter()
    segmenter.push_frame(b"\x00\x00" * 320)
    segmenter.feed(is_speech=True)

    # 持续喂静音直到超过换人阈值。
    event = None
    for _ in range(DEFAULT_TURN_SILENCE_MS // 20 + 1):
        event = segmenter.feed(is_speech=False)
        if event.kind == EVENT_TURN_CHANGE:
            break

    assert event is not None and event.kind == EVENT_TURN_CHANGE, "未触发换人事件"
    assert event.frames == [], "换人时已收集的音频必须被丢弃"


# ----------------------------------------------------------------------
# 固件侧必须有、PC 侧也要有的符号（防止漏实现）
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "contract",
    [item for item in BEHAVIOR_CONTRACTS if item.kind is ContractKind.BEHAVIOR_RULE],
    ids=lambda item: item.contract_id,
)
def test_firmware_declares_the_behavior_symbol(contract: BehaviorContract):
    """行为规则类契约：固件侧必须声明对应的符号。

    为什么：漏声明意味着真机上没实现这个行为，
    而"没实现"不会报错 —— 只表现为行为缺失。
    """
    text = _read(contract.firmware_header)
    assert contract.firmware_symbol in text, (
        f"固件 {contract.firmware_header} 未声明 {contract.firmware_symbol}"
        f"（契约 {contract.contract_id}）"
    )


def test_contract_lookup_by_id():
    """按标识查契约必须可用且找不到时报错。

    为什么：测试与报告都按标识定位契约。
    找不到时静默返回 None 会让"这条契约没人查"变成静默失败。
    """
    assert contract_by_id("state.states").kind is ContractKind.ENUM_SET
    with pytest.raises(KeyError):
        contract_by_id("不存在的契约")
