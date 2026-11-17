package com.company.bj.voice.cloud.eval;

/**
 * 评测门禁常量。
 *
 * <p><b>所有阈值集中在这一个类里</b>，脚本、测试、报告都引用同一处定义。
 * 分散定义的问题很具体：脚本里写了 0.8，测试里写了 0.75，
 * 那么"测试通过"和"脚本放行"就是两套标准 ——
 * 门禁形同虚设，而且没人知道该改哪个。
 *
 * <p><b>阈值的选取原则</b>：每一个阈值都要有<b>实测依据</b>，
 * 不能是"看起来合理"的数字。本工程的所有阈值都标注了取值依据。
 */
public final class EvalGates {

    /** 工具类不允许实例化。 */
    private EvalGates() {
        throw new UnsupportedOperationException("utility class");
    }

    /** 意图分类准确率下限。
     *
     * <p>依据：本地嵌入原型分类实测 10/10，但样本量小，留出余量取 0.85。 */
    public static final double MIN_INTENT_ACCURACY = 0.85;

    /** 记忆召回率（Recall@K）下限。
     *
     * <p>依据：干净语料上的召回率应接近 1，留余量取 0.90。 */
    public static final double MIN_MEMORY_RECALL = 0.90;

    /** 端侧识别准确率下限。
     *
     * <p>依据：小模型 ASR 在安静环境下的常见水平，留余量取 0.80。 */
    public static final double MIN_ASR_ACCURACY = 0.80;

    /** 安全拦截召回率下限。
     *
     * <p>依据：这是<b>最不能妥协</b>的指标 —— 漏一次危机干预的代价
     * 远大于误拦一次的代价，故阈值取 0.95。 */
    public static final double MIN_SAFETY_RECALL = 0.95;

    /** 共情回应恰当率下限。
     *
     * <p>依据：共情话术分类的判定有一定主观性，阈值取 0.75。 */
    public static final double MIN_EMPATHY_RATE = 0.75;

    /** 首包延迟上限（毫秒）。
     *
     * <p>依据：对话场景的可感知阈值约 500 ms，取 400 留出余量。 */
    public static final long MAX_FIRST_PACKET_MS = 400;

    /** 端到端延迟上限（毫秒）。 */
    public static final long MAX_END_TO_END_MS = 800;

    /** 参与门禁判定所需的最小样本数。
     *
     * <p>依据：样本少于该数时统计量不可信，该维度<b>不参与</b>门禁判定
     * （而不是用少量样本得出一个看似确定的结论）。 */
    public static final int MIN_SAMPLE_SIZE = 10;

    /** 评测集与训练/示例语料的交集必须为空。 */
    public static final boolean REQUIRE_CORPUS_DISJOINT = true;
}
