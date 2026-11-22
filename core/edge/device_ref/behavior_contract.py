"""端侧行为基准：固件契约与 PC 侧实现的语义对齐表。

**这个模块解决什么问题**

固件（`device-ref/firmware/include/*.h`）与 PC 模拟端（`core/edge/`）
是同一套端侧行为的两份实现。现有测试守住的是**结构契约** ——
常量对不对、字段名拼没拼错、状态集合一不一致。

但**结构一致不等于行为一致**：固件声明了"打断时保留已识别文本"，
PC 侧实现成保留完整文本；固件声明"置信度低于 0.4 降级为关键词匹配"，
PC 侧实际是低于 0.5。这类分歧**编译通过、测试全绿、真机跑起来才发现**。

本模块把行为契约写成**一份机器可读的清单**：
每条契约声明"固件侧声明的语义"与"PC 侧的参考实现"，
并由 `core/tests/device_ref/test_behavior_contract.py` 逐条核对。

**为什么用"清单 + 生成器"而不是直接写断言**

因为行为契约需要**双向**检查：
1. 固件头文件里声明的语义常量，PC 侧必须有对应且**取值一致**；
2. PC 侧的某个行为，固件头文件里**不能漏掉** ——
   漏掉的那一条在真机上就是没实现。

第 2 条用"从两侧各自抽取，再比对集合"的方式检查，
需要一份共同的清单作为基准。这就是本模块的用途。

**边界：能验什么、不能验什么**

能验（行为正确性）：
- 状态机六态的转移语义（打断、超时、播完）
- 打断时"丢音频、不丢文本"的实际行为
- VAD 与断句的阈值常量
- 意图判定的降级阈值与分流原则

**不能验**（必须真机）：
- 延迟数值的绝对值（PC 是 x86，STM32 是 Cortex-M）
- 栈大小、队列深度、优先级反转
- 功耗与温升
- I2S/DMA 时序与时钟漂移

**这个区分必须写在代码里而不是只写在文档里** ——
文档会被人跳过，断言不会。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ContractKind(Enum):
    """契约条目的类别。

    分类不是为了好看，而是为了让**核对方式**可区分：
    不同类别的核对逻辑不同，混在一起会掩盖某类的缺失。
    """

    #: 数值常量必须两侧相等（例如 VAD 阈值、帧长）。
    NUMERIC_CONSTANT = "numeric_constant"

    #: 枚举取值集合必须两侧相等（例如状态机六态）。
    ENUM_SET = "enum_set"

    #: 语义规则必须两侧一致（例如"打断丢音频不丢文本"）。
    BEHAVIOR_RULE = "behavior_rule"


@dataclass(frozen=True)
class BehaviorContract:
    """一条端侧行为契约。

    @param contract_id 契约标识（稳定，用于报告与定位）
    @param kind 契约类别
    @param description 契约的自然语言描述（面向人）
    @param firmware_header 固件侧声明所在的头文件
    @param firmware_symbol 固件侧常量名或符号名
    @param python_symbol PC 侧的符号名或属性路径
    @param rationale 为什么要守住这条（说明"不做会怎样"）
    """

    contract_id: str
    kind: ContractKind
    description: str
    firmware_header: str
    firmware_symbol: str
    python_symbol: str
    rationale: str


# 端侧行为契约清单。
#
# **这份清单是"行为在 PC 侧验、性能在真机测"这条边界的载体**。
#
# 新增固件接口时**必须**在这里补一条 —— 少了这一条，
# 该行为就既没有 PC 侧参考实现，也没有任何东西提醒要补。
BEHAVIOR_CONTRACTS: tuple[BehaviorContract, ...] = (
    # ------------------------------------------------------------------
    # 音频格式与帧长
    # ------------------------------------------------------------------
    BehaviorContract(
        contract_id="audio.sample_rate",
        kind=ContractKind.NUMERIC_CONSTANT,
        description="采样率必须为 16 kHz",
        firmware_header="vc_audio_task.h",
        firmware_symbol="VC_AUDIO_SAMPLE_RATE_HZ",
        python_symbol="core.edge.audio.negotiation::DEFAULT_FORMAT.sample_rate",
        rationale="采样率不一致时两边都'运行正常'，但识别结果全是错的。",
    ),
    BehaviorContract(
        contract_id="audio.frame_duration",
        kind=ContractKind.NUMERIC_CONSTANT,
        description="帧长必须为 20 ms",
        firmware_header="vc_audio_task.h",
        firmware_symbol="VC_AUDIO_FRAME_DURATION_MS",
        python_symbol="core.edge.audio.sentence::DEFAULT_FRAME_DURATION_MS",
        rationale=(
            "变长帧会让云端分片重组与端侧帧序号对不上，"
            "表现为'偶发丢字'，且只在语音长短不一时出现，极难定位。"
        ),
    ),
    BehaviorContract(
        contract_id="audio.frame_samples",
        kind=ContractKind.NUMERIC_CONSTANT,
        description="单帧采样点数必须与采样率、帧长自洽",
        firmware_header="vc_audio_task.h",
        firmware_symbol="VC_AUDIO_FRAME_SAMPLES",
        # 自洽关系不是"某个常量"，而是"采样率 × 帧长 ÷ 1000"。
        # 因此 PC 侧引用的是采样率与帧长两个常量 ——
        # 期望值由测试按公式算出，不在这里写死。
        python_symbol="core.edge.audio.negotiation::DEFAULT_FORMAT.sample_rate",
        rationale="不自洽时时间戳会漂移，云端无法把分片拼回原始音频。",
    ),
    # ------------------------------------------------------------------
    # VAD 与断句
    # ------------------------------------------------------------------
    BehaviorContract(
        contract_id="vad.speech_probability_threshold",
        kind=ContractKind.NUMERIC_CONSTANT,
        description="语音概率阈值必须为 0.6",
        firmware_header="vc_audio_task.h",
        firmware_symbol="VC_VAD_SPEECH_PROBABILITY_THRESHOLD",
        python_symbol="core.edge.audio.vad::DEFAULT_SPEECH_PROBABILITY_THRESHOLD",
        rationale=(
            "阈值过低会在用户没说话时误触发 —— 机器人反复起播，"
            "比漏检（少识别一句）伤害大得多。"
        ),
    ),
    BehaviorContract(
        contract_id="vad.energy_threshold",
        kind=ContractKind.NUMERIC_CONSTANT,
        description="底噪能量阈值必须为 0.01（归一化 RMS）",
        firmware_header="vc_audio_task.h",
        firmware_symbol="VC_VAD_RMS_THRESHOLD",
        python_symbol="core.edge.audio.vad::DEFAULT_ENERGY_THRESHOLD",
        rationale="能量阈值过高会漏掉轻声说话，漏检会让用户说的话直接消失。",
    ),
    BehaviorContract(
        contract_id="sentence.end_silence",
        kind=ContractKind.NUMERIC_CONSTANT,
        description="句末静音阈值必须为 600 ms",
        firmware_header="vc_audio_task.h",
        firmware_symbol="VC_AUDIO_SEGMENT_END_SILENCE_MS",
        python_symbol="core.edge.audio.sentence::DEFAULT_END_SILENCE_MS",
        rationale=(
            "阈值过短会把一句话切成多段，机器人听到的是残缺的短语；"
            "过长则每次开口都要多等半秒，体感迟钝。"
        ),
    ),
    BehaviorContract(
        contract_id="sentence.turn_silence",
        kind=ContractKind.NUMERIC_CONSTANT,
        description="换人静音阈值必须为 2000 ms",
        firmware_header="vc_audio_task.h",
        firmware_symbol="VC_AUDIO_TURN_CHANGE_SILENCE_MS",
        python_symbol="core.edge.audio.sentence::DEFAULT_TURN_SILENCE_MS",
        rationale=(
            "换人阈值必须显著大于句末阈值，否则用户停顿一下就被当成离开，"
            "半句话被丢弃。"
        ),
    ),
    # ------------------------------------------------------------------
    # 会话状态机
    # ------------------------------------------------------------------
    BehaviorContract(
        contract_id="state.states",
        kind=ContractKind.ENUM_SET,
        description="会话状态机必须恰好是六态",
        firmware_header="vc_state_machine.h",
        firmware_symbol="VC_STATE_*",
        python_symbol="core.edge.session.state_machine::SessionState",
        rationale=(
            "两端状态集不一致时，固件会停在 Python 侧不存在的状态上，"
            "行为随实现而异，最难复现。"
        ),
    ),
    BehaviorContract(
        contract_id="state.interrupt_latency_limit",
        kind=ContractKind.NUMERIC_CONSTANT,
        description="打断响应延迟上限必须为 300 ms",
        firmware_header="vc_state_machine.h",
        firmware_symbol="VC_INTERRUPT_LATENCY_LIMIT_MS",
        python_symbol="core.edge.session.state_machine::DEFAULT_INTERRUPT_LATENCY_MS",
        rationale="用户插话后超过这个时间还没闭嘴，就是体验故障。",
    ),
    BehaviorContract(
        contract_id="state.dwell_timeout",
        kind=ContractKind.NUMERIC_CONSTANT,
        description="状态超时必须为 10000 ms",
        firmware_header="vc_state_machine.h",
        firmware_symbol="VC_DWELL_TIMEOUT_MS",
        python_symbol="core.edge.session.state_machine::DEFAULT_STATE_TIMEOUT_MS",
        rationale=(
            "卡在 WAITING_CLOUD 意味着麦克风再也不听了 —— "
            "用户说什么都没反应。这是最危险的超时。"
        ),
    ),
    # ------------------------------------------------------------------
    # 端侧 ASR
    # ------------------------------------------------------------------
    BehaviorContract(
        contract_id="asr.confidence_scale",
        kind=ContractKind.NUMERIC_CONSTANT,
        description="识别置信度的分母必须为 1000，且与协议一致",
        firmware_header="vc_asr_task.h",
        firmware_symbol="VC_ASR_CONFIDENCE_SCALE",
        # PC 侧的置信度用 0~1 浮点表示，分母隐含为 1。
        # 因此这里比的是"比例"，不是绝对数值 ——
        # 固件的 1000 与 PC 的 1.0 表达同一件事。
        python_symbol="core.edge.intent.detector::1000（PC 侧用 0~1 浮点，比例相同）",
        rationale=(
            "置信度分母不一致时，协议传输的置信度被误解，"
            "意图判定的降级阈值判断全部错位。"
        ),
    ),
    BehaviorContract(
        contract_id="behavior.asr_confidence_must_be_truthful",
        kind=ContractKind.BEHAVIOR_RULE,
        description="识别置信度必须如实上报，不得把'不确定'报成'确定'",
        firmware_header="vc_asr_task.h",
        firmware_symbol="vc_asr_result_t",
        python_symbol="core.edge.intent.detector::IntentDecision.confidence",
        rationale=(
            "意图判定依赖置信度做降级。把'不确定'报成'确定'会让端侧"
            "在识别错误时自信地走错分支，把用户的话当成了别的意思。"
        ),
    ),
    # ------------------------------------------------------------------
    # 意图判定
    # ------------------------------------------------------------------
    BehaviorContract(
        contract_id="intent.keyword_only_threshold",
        kind=ContractKind.NUMERIC_CONSTANT,
        description="置信度不足时降级为关键词匹配的阈值必须与 PC 侧一致",
        firmware_header="vc_intent_task.h",
        firmware_symbol="VC_INTENT_KEYWORD_ONLY_THRESHOLD",
        python_symbol="core.edge.intent.detector::RECOGNITION_CONFIDENCE_THRESHOLD",
        rationale=(
            "阈值不一致时，同一句话在固件上按关键词执行、在模拟端却拒识 —— "
            "开发者以为的行为与真机不一致。"
        ),
    ),
    BehaviorContract(
        contract_id="intent.confidence_scale",
        kind=ContractKind.NUMERIC_CONSTANT,
        description="意图置信度的分母必须为 1000",
        firmware_header="vc_intent_task.h",
        firmware_symbol="VC_INTENT_CONFIDENCE_SCALE",
        python_symbol="core.edge.intent.detector::1000（PC 侧用 0~1 浮点，比例相同）",
        rationale="比例不一致时置信度在协议传输中被误解，阈值判断全部错位。",
    ),
    # ------------------------------------------------------------------
    # 行为规则（非数值，需要专门核对）
    # ------------------------------------------------------------------
    BehaviorContract(
        contract_id="behavior.barge_in_drops_audio_keeps_text",
        kind=ContractKind.BEHAVIOR_RULE,
        description="打断必须丢未播出的音频、保留已识别的文本",
        firmware_header="vc_state_machine.h",
        firmware_symbol="vc_state_machine_on_recognized",
        python_symbol="core.edge.session.state_machine::BargeInEvent.retained_text",
        rationale=(
            "这是陪伴场景最不能接受的失败形态：用户说'等等'，"
            "机器人连同前面那句一起不说了。"
        ),
    ),
    BehaviorContract(
        contract_id="behavior.timeout_returns_to_idle",
        kind=ContractKind.BEHAVIOR_RULE,
        description="任何状态超时后必须回到 IDLE",
        firmware_header="vc_state_machine.h",
        firmware_symbol="vc_state_machine_on_timeout",
        python_symbol="core.edge.session.state_machine::SessionStateMachine.on_timeout",
        rationale="卡在非 IDLE 状态意味着麦克风不再听，用户说什么都没反应。",
    ),
    BehaviorContract(
        contract_id="behavior.local_intent_only_for_reversible",
        kind=ContractKind.BEHAVIOR_RULE,
        description="端侧只执行可逆、低风险的固定指令，其余上云",
        firmware_header="vc_intent_task.h",
        firmware_symbol="handled_locally",
        python_symbol="core.edge.intent.detector::IntentDecision.handled_locally",
        rationale=(
            "不可逆操作（支付、删除）放在端侧没有回滚机会；"
            "端侧判错意图会让机器人做出完全不相干的回应。"
        ),
    ),
    BehaviorContract(
        contract_id="behavior.turn_change_discards_segment",
        kind=ContractKind.BEHAVIOR_RULE,
        description="换人必须丢弃已收集的音频（半句作废）",
        firmware_header="vc_audio_task.h",
        firmware_symbol="vc_audio_task_take_segment",
        python_symbol="core.edge.audio.sentence::SentenceEvent(EVENT_TURN_CHANGE)",
        rationale=(
            "把换人当成句末送出去，机器人会把别人的话当成用户说的复述一遍。"
        ),
    ),
)


def contracts_by_kind(kind: ContractKind) -> tuple[BehaviorContract, ...]:
    """按类别筛选契约。

    @param kind 契约类别
    @return 该类别下的全部契约
    """
    return tuple(item for item in BEHAVIOR_CONTRACTS if item.kind is kind)


def contract_by_id(contract_id: str) -> BehaviorContract:
    """按标识查契约。

    @param contract_id 契约标识
    @return 对应契约
    @throws KeyError 标识不存在时抛出
    """
    for item in BEHAVIOR_CONTRACTS:
        if item.contract_id == contract_id:
            return item
    raise KeyError(f"未知的行为契约：{contract_id}")


# 必须**由真机测量**、因此**不能**在 PC 侧断言的项目。
#
# **这份清单的价值是"排除"**：把"PC 上验不了"的项明确列出来，
# 避免有人试图在 PC 上给它们编一个假的通过结论。
#
# 每项都必须写明"真机上怎么测" —— 写不出来说明这一项还没想清楚，
# 那就不能留在清单里假装是待验证项。
HARDWARE_ONLY_MEASUREMENTS: tuple[tuple[str, str, str], ...] = (
    (
        "interrupt_latency",
        "打断响应延迟的绝对值",
        "真机上从人声起点到静音输出的时间戳差，用 GPIO 翻转或音频 DMA 时间戳测。",
    ),
    (
        "asr_latency_on_device",
        "端侧 ASR 在 Cortex-M 上的识别延迟",
        "真机上从语音段交给识别器到文本产出打时间戳，统计 P50/P95。",
    ),
    (
        "stack_and_queue_depth",
        "任务栈大小与消息队列深度",
        "真机上做栈水位与队列水位的高水位统计，压测后取最大值。",
    ),
    (
        "dma_timing_jitter",
        "I2S/DMA 中断抖动与丢帧率",
        "真机上连续采集数小时，统计帧时间戳间隔的方差与丢帧计数。",
    ),
    (
        "clock_drift",
        "采样时钟漂移",
        "真机上让采样时钟与外部基准比对，长时间运行后统计累计偏差。",
    ),
    (
        "flash_headroom",
        "flash 余量与模型包装入后的剩余空间",
        "真机上读 flash 分区使用量，并实测模型包安装后的剩余空间。",
    ),
    (
        "power_and_thermal",
        "典型与峰值工况的功耗与温升",
        "真机上接功耗仪跑典型对话与峰值推理场景，记录温升曲线。",
    ),
    (
        "ota_real_switch",
        "A/B 分区真实切换、断电、验签失败回滚",
        "真机上执行一次完整升级，并人为制造断电与验签失败各一次。",
    ),
)
