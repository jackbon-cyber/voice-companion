package com.company.bj.voice.cloud.memory.companion;

import java.util.Comparator;
import java.util.List;

/**
 * 召回融合排序器。
 *
 * <p>把多路召回（短期 / 长期 / 情景）的候选合并成一条有序列表。
 *
 * <p><b>排序公式</b>：
 * <pre>
 *   分数 = 倒数排名分 × 时间衰减系数 × 重要度系数
 * </pre>
 *
 * <p><b>为什么用倒数排名（RRF）而不是直接比较相似度</b>：
 * 三路召回的相似度<b>不在同一量纲上</b> —— 长期记忆走向量余弦（0~1），
 * 短期记忆是命中/未命中（0 或 1），情景记忆可能是时间序位。
 * 直接加权求和需要先把三者归一到同一量纲，而这个归一化本身就是主观的。
 * RRF 只用<b>名次</b>，天然免疫量纲差异 —— 这是它被广泛使用的根本原因。
 *
 * <p><b>衰减与重要度是乘性因子而非加性项</b>：加性项会让"高重要度"
 * 盖过"排第一"，导致一条久远的核心事实被一条崭新的次要事实挤下去。
 * 乘性因子保证名次始终是主导项。
 */
public class RecallFusion {

    /** 倒数排名融合的常数。取值 60 是信息检索领域的常用经验值。 */
    public static final double RRF_CONSTANT = 60.0;

    /** 时间衰减的半衰期（毫秒）：默认 30 天。 */
    public static final long DEFAULT_HALF_LIFE_MILLIS = 30L * 24L * 60L * 60L * 1000L;

    /** 最小衰减系数：防止久远记忆被完全压成 0 而永远无法召回。 */
    public static final double MIN_DECAY_FACTOR = 0.1;

    /** 融合后的候选条目。 */
    public record FusedCandidate(
        String id,
        String content,
        int rank,
        double fusionScore,
        double decayFactor,
        double importanceFactor,
        CompanionMemoryCategory category,
        long createdAt) {
    }

    /**
     * 融合多路召回结果。
     *
     * @param routes      各路召回的候选列表，按该路的排名从优到劣排列
     * @param now         当前时间戳，用于计算时间衰减
     * @param halfLifeMillis 时间衰减半衰期
     * @param limit       最终保留条数上限
     * @return 按融合分数降序排列的候选列表
     */
    public List<FusedCandidate> fuse(
        List<List<FusionCandidate>> routes,
        long now,
        long halfLifeMillis,
        int limit) {

        if (routes == null || routes.isEmpty()) {
            return List.of();
        }

        // 同一 id 可能被多路召回。用累加器把各路的贡献合并，
        // 而不是后到覆盖先到 —— 覆盖会让"被更多路召回"的记忆反而分数更低。
        java.util.Map<String, Accumulator> accumulators = new java.util.LinkedHashMap<>();
        for (List<FusionCandidate> route : routes) {
            if (route == null) {
                continue;
            }
            for (int index = 0; index < route.size(); index++) {
                FusionCandidate candidate = route.get(index);
                if (candidate == null) {
                    continue;
                }
                int rank = index + 1;
                Accumulator accumulator = accumulators.computeIfAbsent(candidate.id(),
                    key -> new Accumulator(candidate));
                accumulator.fusionScore += 1.0 / (RRF_CONSTANT + rank);
                accumulator.bestRank = Math.min(accumulator.bestRank, rank);
                accumulator.routeCount++;
            }
        }

        List<FusedCandidate> fused = new java.util.ArrayList<>(accumulators.size());
        for (Accumulator accumulator : accumulators.values()) {
            double decay = decayFactor(accumulator.candidate.createdAt(), now, halfLifeMillis);
            double importance = importanceFactor(accumulator.candidate.weight());
            fused.add(new FusedCandidate(
                accumulator.candidate.id(),
                accumulator.candidate.content(),
                accumulator.bestRank,
                accumulator.fusionScore * decay * importance,
                decay,
                importance,
                accumulator.candidate.category(),
                accumulator.candidate.createdAt()));
        }

        fused.sort(Comparator.comparingDouble(FusedCandidate::fusionScore).reversed());
        return fused.size() <= limit ? List.copyOf(fused) : List.copyOf(fused.subList(0, limit));
    }

    /**
     * 计算时间衰减系数。
     *
     * <p>采用<b>指数半衰期</b>：距今恰好一个半衰期时系数为 0.5。
     * 线性衰减在"很久以前"时会归零，把所有老记忆都压死；
     * 指数衰减则给老记忆留了一条下限通道。
     *
     * @param createdAt     创建时间戳
     * @param now           当前时间戳
     * @param halfLifeMillis 半衰期
     * @return 衰减系数，范围在 {@link #MIN_DECAY_FACTOR} 与 1 之间
     */
    public double decayFactor(long createdAt, long now, long halfLifeMillis) {
        if (halfLifeMillis <= 0L) {
            return 1.0;
        }
        long age = Math.max(0L, now - createdAt);
        double factor = Math.pow(0.5, (double) age / halfLifeMillis);
        return Math.max(MIN_DECAY_FACTOR, factor);
    }

    /**
     * 计算重要度系数。
     *
     * @param weight 重要度权重
     * @return 系数，范围在 0.1 与 2.0 之间
     */
    public double importanceFactor(double weight) {
        if (weight <= 0.0) {
            return 0.1;
        }
        return Math.min(2.0, Math.max(0.1, weight));
    }

    /** 单路的召回候选。 */
    public record FusionCandidate(
        String id,
        String content,
        double weight,
        CompanionMemoryCategory category,
        long createdAt) {
    }

    /** 融合累加器。 */
    private static final class Accumulator {

        /** 该 id 的融合分数。 */
        private double fusionScore;

        /** 该 id 在各路中的最好名次。 */
        private int bestRank = Integer.MAX_VALUE;

        /** 命中该 id 的路数。 */
        private int routeCount;

        /** 该 id 的候选信息，取首次出现的那一条。 */
        private final FusionCandidate candidate;

        Accumulator(FusionCandidate candidate) {
            this.candidate = candidate;
        }
    }
}
