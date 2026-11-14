"""端侧分段耗时采集。

采集五段耗时：VAD、ASR、意图判定、往返时延、首包时延。分段的目的是
**让"慢"落到具体环节**：一个 2 秒的响应里，往返时延占 1.8 秒说明是网络问题，
首包占 1.5 秒说明是云端首字慢 —— 这两者的优化方向完全不同。

百分位用**最近秩法**（``ceil(q * n) - 1``），与上游 ``agent-memory-kb`` 的
``QualityEvaluator.percentile95`` 口径一致：同一套评测数据在两个工程里
算出来的 P95 必须能对上，否则跨工程的数字没有可比性。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

# 样本量低于该值时，统计量不具统计意义，不参与门禁判定。
MIN_SAMPLE_COUNT = 100

# 默认百分位。
DEFAULT_PERCENTILE = 0.95


@dataclass(frozen=True)
class TurnTimings:
    """一轮对话的分段耗时快照。

    各字段为对应指标的中位数（毫秒），无样本时为 0。
    """

    vad_ms: int = 0
    asr_ms: int = 0
    intent_ms: int = 0
    round_trip_ms: int = 0
    first_packet_ms: int = 0

    #: 各指标的样本数。门禁脚本据此判断**哪个指标**样本不足。
    sample_counts: Mapping[str, int] = field(default_factory=dict)

    #: 已采集指标中的最小样本数。回答"已采到的指标里最弱的那个有多少样本"；
    #: 哪个指标完全没采到，由 ``sample_counts`` 中值为 0 的项回答。
    sample_count: int = 0


def percentile(values: list[int], q: float = DEFAULT_PERCENTILE) -> int:
    """按最近秩法计算百分位。

    @param values 样本列表
    @param q 分位，取值区间 (0, 1]
    @return 百分位对应的样本值；样本为空时返回 0
    @throws ValueError 分位不在 (0, 1] 内时抛出
    """
    if not 0 < q <= 1:
        raise ValueError(f"分位必须落在 (0, 1]，得到 {q}")
    if not values:
        return 0
    ordered = sorted(values)
    index = math.ceil(q * len(ordered)) - 1
    safe_index = max(0, min(index, len(ordered) - 1))
    return ordered[safe_index]


class MetricsCollector:
    """分段耗时采集器。"""

    def __init__(self) -> None:
        """构造采集器。"""
        self._vad: list[int] = []
        self._asr: list[int] = []
        self._intent: list[int] = []
        self._round_trip: list[int] = []
        self._first_packet: list[int] = []

    def record_vad(self, ms: int) -> None:
        """记录一次 VAD 耗时。

        @param ms 耗时（毫秒）
        """
        self._vad.append(ms)

    def record_asr(self, ms: int) -> None:
        """记录一次识别耗时。

        @param ms 耗时（毫秒）
        """
        self._asr.append(ms)

    def record_intent(self, ms: int) -> None:
        """记录一次意图判定耗时。

        @param ms 耗时（毫秒）
        """
        self._intent.append(ms)

    def record_round_trip(self, ms: int) -> None:
        """记录一次往返时延。

        @param ms 耗时（毫秒）
        """
        self._round_trip.append(ms)

    def record_first_packet(self, ms: int) -> None:
        """记录一次首包时延。

        @param ms 耗时（毫秒）
        """
        self._first_packet.append(ms)

    def snapshot(self) -> TurnTimings:
        """生成快照。

        各字段取**中位数**：中位数对偶发长尾不敏感，作为"典型体验"更合适；
        P95 由门禁脚本按需从原始样本另行计算。

        ``sample_counts`` 给出**每个指标各自的**样本数 ——
        五个指标的样本数通常不等：离线降级时不上行首包，首包指标就没有样本。
        用其中一个指标代表整体会误判门禁。

        ``sample_count`` 是**有样本的指标中的最小值**（全部指标都无样本时为 0）。
        它回答"已采集到的这些指标里，最弱的那个有多少样本"；
        而"哪个指标根本没采到"由 ``sample_counts`` 里值为 0 的项回答。
        门禁脚本要同时看这两个：只看前者会把"首包指标完全没采到"误判为样本充足。

        @return 分段耗时快照
        """
        counts = {
            "vad": len(self._vad),
            "asr": len(self._asr),
            "intent": len(self._intent),
            "round_trip": len(self._round_trip),
            "first_packet": len(self._first_packet),
        }
        populated = [count for count in counts.values() if count > 0]
        return TurnTimings(
            vad_ms=percentile(self._vad, 0.5),
            asr_ms=percentile(self._asr, 0.5),
            intent_ms=percentile(self._intent, 0.5),
            round_trip_ms=percentile(self._round_trip, 0.5),
            first_packet_ms=percentile(self._first_packet, 0.5),
            sample_counts=MappingProxyType(counts),
            sample_count=min(populated) if populated else 0,
        )

    def reset(self) -> None:
        """清空已采集的样本。"""
        self._vad = []
        self._asr = []
        self._intent = []
        self._round_trip = []
        self._first_packet = []

    def samples_of(self, name: str) -> list[int]:
        """取某个指标的原始样本。

        @param name 指标标识（vad / asr / intent / round_trip / first_packet）
        @return 样本列表；指标名未知时返回空列表
        @throws ValueError 指标名未知时抛出
        """
        buckets = {
            "vad": self._vad,
            "asr": self._asr,
            "intent": self._intent,
            "round_trip": self._round_trip,
            "first_packet": self._first_packet,
        }
        if name not in buckets:
            raise ValueError(f"未知指标名：{name}")
        return list(buckets[name])
