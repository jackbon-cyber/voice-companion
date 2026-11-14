package com.company.bj.voice.cloud.memory.companion;

/**
 * 陪伴域记忆分类。
 *
 * <p>分类结果决定内容<b>去哪里</b>与<b>留不留</b>：
 * <ul>
 *   <li>{@link #RELATIONSHIP_FACT} / {@link #STABLE_PREFERENCE} / {@link #TIME_SENSITIVE_EVENT}
 *       —— 归入长期记忆，跨会话保留；</li>
 *   <li>{@link #CURRENT_EMOTION} —— 归入情景记忆，只在当次会话有效；</li>
 *   <li>{@link #ONE_SHOT_INSTRUCTION} / {@link #SMALL_TALK}
 *       —— <b>不入长期记忆</b>，不占用存储与召回名额。</li>
 * </ul>
 *
 * <p>这个边界刻意<b>不按令牌窗口划分</b>。按窗口划分会让"我妈妈叫李芳"
 * 在长对话末尾被挤出记忆，而它恰恰是最该长期保留的信息。
 */
public enum CompanionMemoryCategory {

    /** 关系事实：家庭成员、称呼、关系等显式陈述。归入长期记忆。 */
    RELATIONSHIP_FACT(true, true),

    /** 稳定偏好：带情感极性的长期喜好。归入长期记忆。 */
    STABLE_PREFERENCE(true, true),

    /** 时效事件：有明确时间范围的计划或约定。归入长期记忆并携带过期时间。 */
    TIME_SENSITIVE_EVENT(true, true),

    /** 当次情绪：这一轮的情绪状态。归入情景记忆。 */
    CURRENT_EMOTION(false, false),

    /** 一次性指令：一次性的设备或动作指令。不入长期记忆。 */
    ONE_SHOT_INSTRUCTION(false, false),

    /** 低信息量寒暄：一般性寒暄。不入长期记忆。 */
    SMALL_TALK(false, false);

    /** 是否归入长期记忆。 */
    private final boolean longTerm;

    /** 是否携带过期时间（仅时效事件有意义）。 */
    private final boolean expirable;

    CompanionMemoryCategory(boolean longTerm, boolean expirable) {
        this.longTerm = longTerm;
        this.expirable = expirable;
    }

    /**
     * 该分类是否归入长期记忆。
     *
     * @return 归入长期记忆返回 {@code true}
     */
    public boolean longTerm() {
        return longTerm;
    }

    /**
     * 该分类是否可能携带过期时间。
     *
     * @return 可能携带过期时间返回 {@code true}
     */
    public boolean expirable() {
        return expirable;
    }
}
