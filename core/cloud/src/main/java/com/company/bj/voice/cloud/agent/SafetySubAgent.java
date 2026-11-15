package com.company.bj.voice.cloud.agent;

import java.util.List;

/**
 * 安全审核子智能体。
 *
 * <p>负责在生成回复之前拦住不该说的内容。
 *
 * <p><b>安全优先级最高</b>（{@link SubAgentArbitrator#PRIORITY_SAFETY}）：
 * 无论哪个处理器生成了什么，只要安全层判定不可说，就不能下发。
 */
public class SafetySubAgent implements SubAgentHandler {

    /** 安全子智能体的优先级。最高。 */
    public static final int PRIORITY = SubAgentArbitrator.PRIORITY_SAFETY;

    /** 安全审核类意图。 */
    public static final String INTENT_SAFETY_REVIEW = "safety_review";

    /** 审核器。 */
    private final SafetyReviewer reviewer;

    /** 拦截后使用的安全话术。 */
    private final String safePhrase;

    /**
     * 构造安全审核子智能体。
     *
     * @param reviewer   审核器
     * @param safePhrase 拦截后使用的安全话术
     */
    public SafetySubAgent(SafetyReviewer reviewer, String safePhrase) {
        this.reviewer = reviewer;
        this.safePhrase = safePhrase;
    }

    @Override
    public SubAgentResult handle(SubAgentRequest request) {
        SafetyReviewer.Review review = reviewer.review(request.text());

        if (review.blocked()) {
            return SubAgentResult.rejected(
                request.intent(), review.reason(), review.safetyLevel());
        }

        if (review.safetyLevel() == SubAgentHandler.SafetyLevel.CAUTION) {
            // 注意级不拦下，但要在结果里标明，让裁决器能优先选更保守的输出。
            return new SubAgentHandler.SubAgentResult(
                safePhrase, request.intent(), review.safetyLevel(), null, false, review.reason());
        }

        return SubAgentResult.of("", request.intent(), "neutral");
    }

    @Override
    public List<String> supportedIntents() {
        return List.of(INTENT_SAFETY_REVIEW);
    }

    @Override
    public int priority() {
        return PRIORITY;
    }

    /**
     * 安全审核器端口。
     *
     * <p>抽成接口是因为审核规则会持续演进（词表、模型、策略），
     * 而子智能体的编排逻辑不该跟着变。
     */
    @FunctionalInterface
    public interface SafetyReviewer {

        /**
         * 审核一段文本。
         *
         * @param text 待审核文本
         * @return 审核结论
         */
        Review review(String text);

        /**
         * 审核结论。
         *
         * @param safetyLevel 安全等级
         * @param blocked     是否必须拦下
         * @param reason      判定理由
         */
        record Review(
            SubAgentHandler.SafetyLevel safetyLevel, boolean blocked, String reason) {

            /**
             * 构造一个"安全通过"的结论。
             *
             * @return 审核结论
             */
            public static Review safe() {
                return new Review(SubAgentHandler.SafetyLevel.SAFE, false, "无风险");
            }
        }
    }
}
