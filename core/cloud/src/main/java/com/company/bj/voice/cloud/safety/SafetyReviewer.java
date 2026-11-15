package com.company.bj.voice.cloud.safety;

import java.util.List;

/**
 * 安全审核器端口。
 *
 * <p>两个方向：
 * <ul>
 *   <li><b>输入审核</b> —— 用户说的话是否需要拒答或转安全话术；</li>
 *   <li><b>输出审核</b> —— 机器人生成的回复是否该下发。</li>
 * </ul>
 *
 * <p>抽成接口是因为审核规则会持续演进（词表、模型、策略），
 * 而调用编排不该跟着变。
 */
public interface SafetyReviewer {

    /**
     * 审核用户输入。
     *
     * @param text 用户文本
     * @return 审核结论
     */
    Review reviewInput(String text);

    /**
     * 审核机器人输出。
     *
     * @param text 机器人回复
     * @return 审核结论
     */
    Review reviewOutput(String text);

    /**
     * 审核结论。
     *
     * @param level  风险等级
     * @param blocked 是否必须拦下
     * @param reason  判定理由
     * @param category 风险类别
     */
    record Review(RiskLevel level, boolean blocked, String reason, RiskCategory category) {

        /**
         * 构造一个"安全通过"的结论。
         *
         * @return 审核结论
         */
        public static Review safe() {
            return new Review(RiskLevel.NONE, false, "无风险", RiskCategory.NONE);
        }

        /**
         * 判断是否需要进入危机干预流程。
         *
         * @return 需要危机干预返回 {@code true}
         */
        public boolean crisis() {
            return category == RiskCategory.CRISIS;
        }
    }

    /**
     * 风险等级。
     */
    enum RiskLevel {

        /** 无风险。 */
        NONE,

        /** 低风险：可正常回复。 */
        LOW,

        /** 中风险：需谨慎回复。 */
        MEDIUM,

        /** 高风险：必须拦下。 */
        HIGH
    }

    /**
     * 风险类别。
     */
    enum RiskCategory {

        /** 无风险。 */
        NONE,

        /** 一般敏感内容。 */
        SENSITIVE,

        /** 危机信号（自伤、伤人或极端绝望）。 */
        CRISIS,

        /** 医疗、法律、金融等专业领域（不应由陪伴机器人给确定答案）。 */
        PROFESSIONAL
    }
}
