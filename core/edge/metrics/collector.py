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

# 微秒转毫秒的缩放因子。
MICROS_PER_MILLI = 1000

# 微秒转秒的缩放因子。
MICROS_PER_SECOND = 1_000_000

# 置信度分桶阈值：高置信度下界（含）。
CONFIDENCE_HIGH_THRESHOLD = 0.9

# 置信度分桶阈值：中等置信度下界（含）。低于该值为低置信度。
CONFIDENCE_MEDIUM_THRESHOLD = 0.7


def _micros_to_millis(micros: int) -> float:
    """把微秒折算成毫秒，保留一位小数的精度。

    按整数取整会让几十微秒的操作全部变成 0 —— 报告里一排 0 没有任何信息量，
    还会让人误以为"这一步不耗时"。
    这里保留到 0.1 毫秒：再细的精度对"这步慢不慢"这个问题没有意义，
    而浮点数带来的显示噪声用一位小数即可控住。

    @param micros 耗时（微秒）
    @return 耗时（毫秒，保留一位小数）
    """
    return round(micros / MICROS_PER_MILLI, 1)


@dataclass(frozen=True)
class TurnTimings:
    """一轮对话的分段耗时快照。

    各字段为对应指标的中位数（毫秒），无样本时为 0。

    字段类型为浮点：亚毫秒级的操作（VAD、意图判定）按毫秒取整会全部变成 0，
    报告里一排 0 既没有信息量，又会让人误以为"这一步不耗时"。
    """

    vad_ms: float = 0
    asr_ms: float = 0
    intent_ms: float = 0
    round_trip_ms: float = 0
    first_packet_ms: float = 0

    #: 端侧生成速度（token/秒）。无样本时为 0。
    generation_tokens_per_second: float = 0

    #: 置信度分桶：高置信度样本数（>= 0.9）。
    confidence_high: int = 0

    #: 置信度分桶：中等置信度样本数（[0.7, 0.9)）。
    confidence_medium: int = 0

    #: 置信度分桶：低置信度样本数（< 0.7）。
    confidence_low: int = 0

    #: 各指标的样本数。门禁脚本据此判断**哪个指标**样本不足。
    sample_counts: Mapping[str, int] = field(default_factory=dict)

    #: 已采集指标中的最小样本数。回答"已采到的指标里最弱的那个有多少样本"；
    #: 哪个指标完全没采到，由 ``sample_counts`` 中值为 0 的项回答。
    sample_count: int = 0


def percentile(values: list[float], q: float = DEFAULT_PERCENTILE) -> float:
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
        self._vad: list[float] = []
        self._asr: list[float] = []
        self._intent: list[float] = []
        self._round_trip: list[float] = []
        self._first_packet: list[float] = []
        self._generation_speeds: list[float] = []
        self._confidences: list[float] = []

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

    def record_vad_micros(self, micros: int) -> None:
        """记录一次 VAD 耗时（微秒）。

        **为什么需要微秒入口**：VAD、意图判定这类操作在 PC 上只花几十微秒。
        按毫秒取整会让它们**全部变成 0** —— 报告里一排 0 没有任何信息量，
        还会让人误以为"这一步不耗时"。
        累计用微秒、报告时才折算成毫秒（保留一位小数），
        既不丢信息，报告又仍然以毫秒为单位。

        @param micros 耗时（微秒）
        """
        self._vad.append(_micros_to_millis(micros))

    def record_asr_micros(self, micros: int) -> None:
        """记录一次识别耗时（微秒）。

        @param micros 耗时（微秒）
        """
        self._asr.append(_micros_to_millis(micros))

    def record_intent_micros(self, micros: int) -> None:
        """记录一次意图判定耗时（微秒）。

        @param micros 耗时（微秒）
        """
        self._intent.append(_micros_to_millis(micros))

    def record_generation(self, micros: int, tokens: int) -> None:
        """记录一次端侧生成。

        **为什么用"每秒 token 数"而不是毫秒**：毫秒只能说明"这次生成花了多久"，
        说明不了"模型有多快"—— 生成 5 个字花 100 毫秒与生成 50 个字花
        100 毫秒是两种完全不同的能力。只有归一化到 token 才可比较。

        @param micros 生成耗时（微秒）
        @param tokens 生成的 token 数
        """
        if tokens <= 0 or micros <= 0:
            # 生成 0 个 token 或耗时为 0 时速度无意义，不参与统计。
            return
        self._generation_speeds.append(tokens * MICROS_PER_SECOND / micros)

    def record_confidence(self, confidence: float) -> None:
        """记录一次识别置信度。

        **为什么记录分布而不是平均值**：平均值会掩盖
        "绝大多数很自信、少数极不自信"这种关键形态 ——
        后者恰恰是拒识机制要拦下的部分，只有分桶统计才看得见。

        @param confidence 置信度，取值区间为 0 到 1
        @throws ValueError 置信度不在 [0, 1] 区间时抛出
        """
        if not 0.0 <= confidence <= 1.0:
            raise ValueError(f"置信度必须落在 [0, 1]，得到 {confidence}")
        self._confidences.append(confidence)

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
            "generation": len(self._generation_speeds),
            "confidence": len(self._confidences),
        }
        populated = [count for count in counts.values() if count > 0]
        high, medium, low = self._confidence_buckets()
        return TurnTimings(
            vad_ms=percentile(self._vad, 0.5),
            asr_ms=percentile(self._asr, 0.5),
            intent_ms=percentile(self._intent, 0.5),
            round_trip_ms=percentile(self._round_trip, 0.5),
            first_packet_ms=percentile(self._first_packet, 0.5),
            generation_tokens_per_second=percentile(self._generation_speeds, 0.5),
            confidence_high=high,
            confidence_medium=medium,
            confidence_low=low,
            sample_counts=MappingProxyType(counts),
            sample_count=min(populated) if populated else 0,
        )

    def _confidence_buckets(self) -> tuple[int, int, int]:
        """按固定阈值把置信度样本分桶。

        @return (高置信度条数, 中等置信度条数, 低置信度条数)
        """
        high = sum(1 for value in self._confidences if value >= CONFIDENCE_HIGH_THRESHOLD)
        medium = sum(
            1
            for value in self._confidences
            if CONFIDENCE_MEDIUM_THRESHOLD <= value < CONFIDENCE_HIGH_THRESHOLD
        )
        low = sum(1 for value in self._confidences if value < CONFIDENCE_MEDIUM_THRESHOLD)
        return high, medium, low

    def reset(self) -> None:
        """清空已采集的样本。"""
        self._vad = []
        self._asr = []
        self._intent = []
        self._round_trip = []
        self._first_packet = []
        self._generation_speeds = []
        self._confidences = []

    def samples_of(self, name: str) -> list[float]:
        """取某个指标的原始样本。

        @param name 指标标识（vad / asr / intent / round_trip / first_packet /
            generation / confidence）
        @return 样本列表；指标名未知时返回空列表
        @throws ValueError 指标名未知时抛出
        """
        buckets = {
            "vad": self._vad,
            "asr": self._asr,
            "intent": self._intent,
            "round_trip": self._round_trip,
            "first_packet": self._first_packet,
            "generation": self._generation_speeds,
            "confidence": self._confidences,
        }
        if name not in buckets:
            raise ValueError(f"未知指标名：{name}")
        return list(buckets[name])
