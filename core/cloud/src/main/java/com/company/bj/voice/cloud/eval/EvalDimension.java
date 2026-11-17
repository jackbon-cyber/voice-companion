package com.company.bj.voice.cloud.eval;

/**
 * 评测维度。
 */
public enum EvalDimension {

    /** 意图分类（云端）。 */
    INTENT(Runner.CLOUD),

    /** 记忆召回（云端）。 */
    MEMORY_RECALL(Runner.CLOUD),

    /** 端侧识别（端侧）。 */
    ASR(Runner.EDGE),

    /** 安全审核（云端）。 */
    SAFETY(Runner.CLOUD),

    /** 共情回应（云端）。 */
    EMPATHY(Runner.CLOUD);

    /** 评测执行侧。 */
    public enum Runner {

        /** 由 Java 云端评测器执行。 */
        CLOUD,

        /** 由 Python 端侧评测器执行。 */
        EDGE
    }

    /** 评测执行侧。 */
    private final Runner runner;

    EvalDimension(Runner runner) {
        this.runner = runner;
    }

    /**
     * 返回该维度由哪一侧执行。
     *
     * @return 执行侧
     */
    public Runner runner() {
        return runner;
    }

    /**
     * 判断该维度是否由云端评测器执行。
     *
     * @return 云端执行返回 {@code true}
     */
    public boolean cloudSide() {
        return runner == Runner.CLOUD;
    }

    /**
     * 返回该维度的度量名称。
     *
     * @return 度量名称
     */
    public String metricName() {
        return switch (this) {
            case INTENT -> "intent_accuracy";
            case MEMORY_RECALL -> "memory_recall_at_k";
            case ASR -> "asr_accuracy";
            case SAFETY -> "safety_recall";
            case EMPATHY -> "empathy_rate";
        };
    }

    /**
     * 判断该维度是否要求<b>评测集与生产语料严格不相交</b>。
     *
     * <p><b>这个区分是必要的，不是妥协</b>：交集禁令的目的是
     * "别拿训练时见过的句子来测泛化"。但不同维度的"训练语料"含义完全不同：
     *
     * <ul>
     *   <li><b>意图与记忆召回</b>：模型靠<b>学习</b>产出结果。
     *       评测句一旦与原型句或记忆原文重复，
     *       测到的就是背诵而不是泛化 —— 必须严格不相交。</li>
     *   <li><b>安全与共情</b>：审核与情绪判定靠的是<b>词表规则</b>。
     *       评测样本<b>本来就必须触发这些规则</b> ——
     *       造出一堆规则覆盖不到的句子，测出来的召回率与真实能力无关。
     *       这类维度的重叠是<b>设计使然</b>，不是数据泄漏。</li>
     * </ul>
     *
     * <p>对规则型维度，重叠情况改为在报告中<b>如实列出</b>，
     * 让人能看见"哪几条评测句与规则字面重合"，
     * 而不是把它藏起来或假装没这回事。
     *
     * @return 要求严格不相交返回 {@code true}
     */
    public boolean requiresCorpusDisjoint() {
        return this == INTENT || this == MEMORY_RECALL;
    }
}
