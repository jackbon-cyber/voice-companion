"""端侧意图规则表。

规则表覆盖**高频固定指令** —— 这类意图的识别成本几乎为零（关键词匹配），
却能省掉一次上云往返。命中规则且置信度足够时，端侧直接执行，不上云。

规则表刻意保持小而确定：宁可漏判（走云端），也不误判（端侧把闲聊当成
"停止说话"，用户说的话直接被吞掉）。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 规则命中时的默认置信度。规则表是确定性的，置信度固定。
RULE_CONFIDENCE = 0.9


@dataclass(frozen=True)
class IntentRule:
    """一条固定的意图规则。"""

    intent: str
    keywords: tuple[str, ...]
    slots: dict[str, str] = field(default_factory=dict)
    confidence: float = RULE_CONFIDENCE


# 固定指令规则表。关键词用用户最可能说出的措辞，不是内部术语。
DEFAULT_RULES: tuple[IntentRule, ...] = (
    IntentRule(
        intent="set_volume",
        keywords=("音量", "声音大一点", "声音小一点", "大声", "小声"),
        slots={"parameter": "volume"},
    ),
    IntentRule(
        intent="stop_speaking",
        # 只用多字短语，不用单字"停"：单字会命中"停下来休息""停在半路"
        # "我想停一下"等日常表达，把闲聊当成停止指令，用户的话会直接被吞掉。
        keywords=("别说了", "不要说了", "别说话", "停止说话", "闭嘴", "安静", "别念了"),
    ),
    IntentRule(
        intent="play_music",
        keywords=("放音乐", "播放音乐", "来首歌", "听歌"),
    ),
    IntentRule(
        intent="check_time",
        keywords=("几点", "现在时间", "什么时候"),
    ),
    IntentRule(
        intent="weather_query",
        keywords=("天气", "气温", "下雨"),
    ),
    IntentRule(
        intent="check_device_status",
        keywords=("状态", "电量", "剩余", "还能用多久"),
    ),
)
