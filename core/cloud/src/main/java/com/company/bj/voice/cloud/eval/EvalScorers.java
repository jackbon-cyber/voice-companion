package com.company.bj.voice.cloud.eval;

import com.company.bj.voice.cloud.intent.IntentClassifier;
import com.company.bj.voice.cloud.intent.IntentSamples;
import com.company.bj.voice.cloud.memory.LongTermStore;
import com.company.bj.voice.cloud.memory.MemoryRecord;
import com.company.bj.voice.cloud.memory.ScopeResolver;
import com.company.bj.voice.cloud.safety.SafetyReviewer;
import java.util.List;

/**
 * 评测打分器工厂。
 *
 * <p><b>关键约束：打分器必须调用真实的生产组件</b>，不得用桩实现。
 * 用桩测出来的准确率衡量的是"桩有多准"，与系统能力无关 ——
 * 这类数字拿去求职演示是自欺欺人。
 *
 * <p>因此本类的每个工厂方法都要求传入生产组件实例
 * （意图分类器、记忆存储、安全审核器），由调用方注入。
 * 组件不可用时**让异常冒泡**，而不是静默返回"不通过"——
 * 静默降级会让"服务没起"被误读成"指标不达标"。
 */
public class EvalScorers {

    /** 意图维度的期望值：意图标识。 */
    public static final String EXPECTED_INTENT = "intent";

    /** 安全维度的期望值：{@code blocked} 或 {@code safe}。 */
    public static final String EXPECTED_BLOCKED = "blocked";

    /** 安全维度的期望值：{@code safe}。 */
    public static final String EXPECTED_SAFE = "safe";

    /** 工具类不允许实例化。 */
    private EvalScorers() {
        throw new UnsupportedOperationException("utility class");
    }

    /**
     * 构造意图维度打分器。
     *
     * <p>用生产代码里的原型意图分类器判定，命中即算正确。
     * 分类器返回 {@code unknown} 时算失败 —— 评测集里的句子都是明确意图，
     * 判不出意图就是没答对。
     *
     * @param classifier 生产意图分类器
     * @return 打分器
     */
    public static EvalExecutor.Scorer intent(IntentClassifier classifier) {
        return sample -> {
            IntentClassifier.Classification classification = classifier.classify(sample.input());
            return IntentClassifier.UNKNOWN_INTENT.equals(classification.intent())
                ? IntentClassifier.UNKNOWN_INTENT
                : classification.intent();
        };
    }

    /**
     * 构造安全维度打分器。
     *
     * <p>期望值为 {@code blocked} 时，要求审核结论<b>必须拦下</b>；
     * 期望值为 {@code safe} 时，要求<b>不得拦下</b>。
     *
     * <p><b>打分器的返回值必须与期望值同一套词汇</b>（{@code blocked} / {@code safe}），
     * 否则执行器的相等比较会永远判失败，而失败明细里会出现
     * "期望=blocked 实际=MATCH" 这种无法解读的文本。
     *
     * <p><b>安全维度的指标是召回率而不是准确率</b>：
     * 拦住一条安全的话代价（用户被无故拒答）远小于
     * 漏掉一条危机信号（用户失去求助渠道）。因此这个维度的门禁
     * 只看"该拦的都拦住了吗"，误拦由另一条约束兜底。
     *
     * @param reviewer 生产安全审核器
     * @return 打分器
     */
    public static EvalExecutor.Scorer safety(SafetyReviewer reviewer) {
        return sample -> reviewer.reviewInput(sample.input()).blocked()
            ? EXPECTED_BLOCKED
            : EXPECTED_SAFE;
    }

    /**
     * 构造共情维度打分器。
     *
     * <p>打分器返回<b>实际判定的情感标签</b>（与期望值同一套词汇），
     * 由执行器做相等比较。
     *
     * <p><b>共情维度的判据是"该说安慰话时有没有说安慰话"</b>：
     * 期望值为非 {@code neutral} 的情绪标签时，要求判定出的情绪与之相符；
     * 期望值为 {@code neutral} 时，要求判定结果也是 {@code neutral}。
     *
     * <p>这是<b>恰当率</b>而非准确率：判错情绪标签的后果是语气略偏，
     * 不是系统错误，因此阈值低于安全维度。
     *
     * @param classifier 情绪分类器
     * @return 打分器
     */
    public static EvalExecutor.Scorer empathy(
        com.company.bj.voice.cloud.memory.companion.EmotionClassifier classifier) {

        return sample -> classifier.classify(sample.input());
    }

    /**
     * 返回意图示例句库，用于评测集的语料交集检查。
     *
     * @return 语料列表
     */
    public static List<String> intentCorpus() {
        return IntentSamples.keywords();
    }
}
