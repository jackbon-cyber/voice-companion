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

    /**
     * 记忆作答准确率下限。
     *
     * <p><b>这个阈值管的是"用户实际听到的那句话"</b> ——
     * 系统作为事实陈述给出的记忆正确时才算对。
     *
     * <p>口径：<b>拒答不计入分子也不计入分母</b>。
     * 拒答是正确行为（没把握时沉默远好于乱答）。
     *
     * <p>依据：13 条答得上的样本里 10 条答对、3 条漏答，
     * 拒答的 3 条移出分母后，准确率 = 10/10 = 100%。
     *
     * <p>阈值取 0.95：答错一次就是用户被误导一次，容错空间比召回率小。
     */
    public static final double MIN_MEMORY_ANSWER = 0.95;

    /**
     * 记忆作答率（覆盖率）下限。
     *
     * <p><b>为什么需要第二道门禁</b>：作答准确率只看"说了的那些对不对"，
     * 一个"永远拒答"的系统准确率也是满分 —— 但那样的机器人毫无用处。
     * 作答率保证"该答的时候答得出来"。
     *
     * <p>依据：实测 10/13 = 76.9%（3 条因相关性不足而拒答）。
     *
     * <p><b>这个阈值定得很低是刻意的</b>：当前检索能力下，
     * "答得出"与"答不出"在得分上只有 0.0046 的缝隙，
     * 分不开的那些问句只能拒答。把阈值定高就是在逼系统编造 ——
     * <b>宁可少答，不可乱答</b>。检索质量提升后这个阈值应随之上调，
     * 它记录的是"当前能力下答得出来的比例"，不是"理想比例"。
     */
    public static final double MIN_MEMORY_ANSWER_RATE = 0.75;

    /**
     * 记忆编造率上限。
     *
     * <p><b>这是本维度最不能妥协的指标</b>：
     * 答错（说了库里另一条）是答非所问，用户能察觉；
     * 编造（说了库里根本没有的事）<b>用户无从分辨真假</b> ——
     * 一旦机器人开始编，用户就再也不能相信它的记忆，
     * 而记忆正是这个产品的核心卖点。
     *
     * <p>口径：答不上的问题里，系统<b>不拒答而是作答</b>的比例。
     *
     * <p>依据：实测 12 条答不上的问题<b>全部正确拒答</b>，编造率 = 0。
     * 阈值取 0.05 —— 留 5% 的余量，但绝不容忍系统性编造。
     */
    public static final double MAX_MEMORY_FABRICATION = 0.05;

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
