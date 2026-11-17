package com.company.bj.voice.cloud.eval;

import com.company.bj.voice.cloud.memory.LongTermStore;
import com.company.bj.voice.cloud.memory.MemoryRecord;
import com.company.bj.voice.cloud.memory.MemoryScope;
import com.company.bj.voice.cloud.memory.ScopeResolver;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * 记忆召回维度的打分器。
 *
 * <p><b>为什么单独成类而不是一个方法</b>：
 * 记忆召回必须<b>分两阶段</b>执行 —— 先把全部样本的记忆原文写进记忆库，
 * 再逐条用问句去检索。
 *
 * <p><b>为什么必须分两阶段</b>：若边写边检索，
 * 先写进去的样本会占掉检索名额（{@code topK} 是有限的），
 * 后面样本的召回率会因为「记忆库里已经有别人的东西」而下降 ——
 * 测出来的数字随样本顺序波动，无法复现。
 * 严格的做法是：全部写入完成后才开始检索，
 * 每一轮的检索环境完全一致。
 *
 * <p><b>问句与记忆原文是不同表述</b>：
 * 评测集的第四段给出记忆原文，第三段给出问句。
 * 用同一句话写入再检索，召回率必然是 1.0 ——
 * 那测的是字符串相等，不是语义召回能力。
 *
 * <p><b>评测数据写入专用作用域，且每次评测前先清空</b>：
 * 评测会向记忆库写入一次性数据，而检索的 {@code topK} 名额有限。
 * 若沿用生产作用域，上一轮遗留的记录会挤占本轮的召回名额，
 * 实测值随运行次数单调下滑 —— 指标不可复现，门禁也就失去意义。
 * 用专用作用域 + 评测前清空，可保证<b>任意次运行的检索环境完全一致</b>，
 * 同时不影响生产用户的记忆数据。
 */
public class MemoryRecallScorer implements EvalExecutor.Scorer {

    /** 召回成功的标记。 */
    public static final String RECALLED = "RECALLED";

    /** 召回失败的标记。 */
    public static final String MISSED = "MISSED";

    /** 评测专用作用域的租户标识。 */
    public static final String EVAL_TENANT_ID = "evaluation";

    /** 评测专用作用域的主体标识。 */
    public static final String EVAL_OWNER_KEY = "evaluation";

    /** 长期记忆存储。 */
    private final LongTermStore store;

    /** 作用域解析器。 */
    private final ScopeResolver resolver;

    /** 检索返回条数上限。 */
    private final int topK;

    /** 评测作用域。 */
    private final MemoryScope evalScope;

    /**
     * 构造记忆召回打分器。
     *
     * @param store    长期记忆存储
     * @param resolver 作用域解析器
     * @param topK     检索返回条数上限
     */
    public MemoryRecallScorer(LongTermStore store, ScopeResolver resolver, int topK) {
        this.store = store;
        this.resolver = resolver;
        this.topK = topK;
        this.evalScope = MemoryScope.of(EVAL_TENANT_ID, EVAL_OWNER_KEY);
    }

    /**
     * 返回评测作用域。
     *
     * <p>对外暴露是为了让调用方（如 CLI）能���清"评测数据落在哪里"，
     * 而不是只能从报告里猜。
     *
     * @return 评测作用域
     */
    public MemoryScope evalScope() {
        return evalScope;
    }

    /**
     * 写入全部样本的记忆原文。
     *
     * <p><b>必须先调用本方法，再执行检索</b>。
     *
     * <p><b>写入前先清空评测作用域</b>：上一轮遗留的记录会挤占 {@code topK} 名额，
     * 让本轮的召回率随运行次数下滑。清空后本轮的检索环境与首次运行完全一致。
     *
     * @param dataset 评测集
     * @return 实际写入的记忆原文条数
     */
    public int prepare(EvalDataset dataset) {
        List<EvalSample> samples = dataset.samplesOf(EvalDimension.MEMORY_RECALL);
        Set<String> corpus = new LinkedHashSet<>();
        for (EvalSample sample : samples) {
            corpus.add(sample.corpusOrInput());
        }

        return resolver.withScopeResult(evalScope, () -> {
            store.clearCurrentScope();
            int written = 0;
            for (String content : corpus) {
                store.remember(content);
                written++;
            }
            return written;
        });
    }

    @Override
    public String score(EvalSample sample) {
        return resolver.withScopeResult(evalScope, () -> {
            String expected = sample.corpusOrInput();
            List<MemoryRecord> found = store.search(sample.input(), topK);
            for (MemoryRecord record : found) {
                if (record.content().equals(expected)) {
                    return RECALLED;
                }
            }
            return MISSED;
        });
    }
}
