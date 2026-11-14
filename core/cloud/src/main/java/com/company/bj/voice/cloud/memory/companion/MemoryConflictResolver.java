package com.company.bj.voice.cloud.memory.companion;

import java.util.List;

/**
 * 记忆冲突消解器。
 *
 * <p>两条同类事实冲突时的判定顺序是<b>固定的</b>：置信度 → 时间 → 并列保留。
 * 顺序不能调换 —— 先比时间会让"我早就说过 X"压过"我刚更正过 X"，
 * 而抽取置信度正是用来表达"我刚更正过"的。
 *
 * <p><b>无法判定时并列保留</b>，而不是静默丢弃其中一方：
 * 丢弃意味着用户的某句话凭空消失，而用户不会知道哪句被丢了。
 * 并列保留 + 消歧标记把决定权交回给后续的上下文装配环节。
 */
public class MemoryConflictResolver {

    /** 置信度差小于该值时视为"置信度接近"，转而比较时间。 */
    public static final double CONFIDENCE_TIE_THRESHOLD = 0.05;

    /**
     * 消解两条冲突记忆。
     *
     * @param left  左侧记忆
     * @param right 右侧记忆
     * @return 消解结果
     */
    public ConflictResolution resolve(CompanionMemory left, CompanionMemory right) {
        if (left == null || right == null) {
            throw new IllegalArgumentException("conflict candidates must not be null");
        }

        double confidenceGap = left.confidence() - right.confidence();
        if (Math.abs(confidenceGap) > CONFIDENCE_TIE_THRESHOLD) {
            CompanionMemory winner = confidenceGap > 0 ? left : right;
            CompanionMemory loser = confidenceGap > 0 ? right : left;
            return new ConflictResolution(List.of(winner), loser, ResolutionReason.HIGHER_CONFIDENCE);
        }

        if (left.createdAt() != right.createdAt()) {
            CompanionMemory winner = left.createdAt() > right.createdAt() ? left : right;
            CompanionMemory loser = left.createdAt() > right.createdAt() ? right : left;
            return new ConflictResolution(List.of(winner), loser, ResolutionReason.NEWER_TIMESTAMP);
        }

        return new ConflictResolution(List.of(left, right), null, ResolutionReason.KEEP_BOTH);
    }

    /**
     * 消解结果的判定依据。
     */
    public enum ResolutionReason {

        /** 置信度明显更高者胜出。 */
        HIGHER_CONFIDENCE,

        /** 置信度接近，时间较新者胜出。 */
        NEWER_TIMESTAMP,

        /** 置信度与时间均无法区分，并列保留。 */
        KEEP_BOTH
    }

    /**
     * 消解结果。
     *
     * @param winners 胜出项；并列保留时含两条
     * @param loser   被淘汰项；并列保留时为 {@code null}
     * @param reason  判定依据
     */
    public record ConflictResolution(
        List<CompanionMemory> winners,
        CompanionMemory loser,
        ResolutionReason reason) {

        /**
         * 判断本次消解是否产生了消歧标记。
         *
         * @return 并列保留返回 {@code true}
         */
        public boolean requiresDisambiguation() {
            return reason == ResolutionReason.KEEP_BOTH;
        }
    }
}
