package com.company.bj.voice.cloud.eval;

import com.company.bj.voice.cloud.memory.LongTermStore;
import com.company.bj.voice.cloud.memory.MemoryRecord;
import com.company.bj.voice.cloud.memory.MemoryScope;
import com.company.bj.voice.cloud.memory.ScopeResolver;
import com.company.bj.voice.cloud.memory.ScoredMemoryRecord;
import com.company.bj.voice.cloud.memory.ScoredMemorySearch;
import com.company.bj.voice.cloud.memory.companion.MemoryRelevancePolicy;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * 记忆<b>作答</b>维度的打分器。
 *
 * <p><b>这个维度补的是 Recall@K 补不了的那个洞</b>：
 * Recall@K 问的是"正确答案有没有出现在前 K 条里"，
 * 而产品真正回复用户的是<b>排序第一条</b>。
 * 这两件事在 K 较大时可以差得很远 ——
 * 实测 13 条记忆召回样本上，Recall@6 是 13/13 = 100%，
 * 而排序第一条答对的是 12/13 = 92.3%。
 *
 * <p>也就是说：<b>Recall@K 度量的是一个用户永远看不到的数字</b>。
 * 一个把"正确答案排在第 3 位"的系统能拿到满分，
 * 而用户听到的是排第一的那条 —— 很可能答非所问。
 *
 * <p><b>本维度怎么打分</b>：把产品真实的作答口径原样搬过来 ——
 * 走 {@link MemoryRelevancePolicy} 的相关性准入，
 * 取准入通过的那一条作为"系统会说的话"，再判断它对不对。
 *
 * <p><b>四种判定与它们的意义</b>：
 * <ul>
 *   <li><b>ANSWERED</b> —— 作答了，且说的正是期望的那条记忆。正确；</li>
 *   <li><b>WRONG</b> —— 作答了，但说的是另一条记忆。
 *       用户听到了一句看起来有依据、实则答非所问的话；</li>
 *   <li><b>FABRICATED</b> —— <b>库里根本没有对应事实</b>，系统却说了点什么。
 *       <b>这是最严重的失败</b>：用户听到了一句库里不存在的话，
 *       而且无从分辨真假。机器人一旦开始编造，用户就再也不能相信它的记忆；</li>
 *   <li><b>拒答</b> —— 没有作答，如实说"没有记录"。
 *       <b>这不算失败</b>：没把握时沉默远好于乱答。
 *       它被标记为 {@link EvalExecutor#NON_APPLICABLE}，
 *       <b>既不进准确率的分子也不进分母</b>。</li>
 * </ul>
 *
 * <p><b>为什么拒答不算失败</b>：陪伴场景里"我不确定"是可接受的，
 * "记错了"是不可接受的。用户会纠正前者，但后者会让用户不再信任机器人的记忆 ——
 * 而记忆正是这个产品的核心卖点。
 *
 * <p><b>评测集必须同时包含"答得上"与"答不上"两类问题</b>：
 * 只测答得上的问题时，<b>永远拒答</b>的系统也能拿满分，门禁形同虚设。
 * 加上答不上的那组之后，"拒答"第一次有了可衡量的价值 ——
 * 对答不上的问题拒答 = 正确，作答 = 编造。
 *
 * <p><b>这个维度的门禁价值</b>：它要求产品<b>必须</b>在没把握时拒答。
 * 实测（相关性下限 0.529，留出集推导）：答得上的 13 条里 10 条答对、
 * 3 条漏答；答不上的 12 条<b>全部正确拒答</b>，零编造。
 * 把下限调到 0.476 时，答不上的那组会有 9 条被当成答案 ——
 * <b>系统开始编造</b>，门禁拦下。
 *
 * <p><b>拒答率不能被这个维度掩盖</b>：一个"永远拒答"的系统，
 * 分数会很高但覆盖率会塌。所以<b>覆盖率（作答率）由 {@link EvalRunner} 单独把关</b>，
 * 两道判据一起构成"既不乱答、也不装死"。
 *
 * <p><b>三个数各自的口径</b>（混用会得出矛盾的结论）：
 * <ul>
 *   <li><b>作答准确率</b> = 答对的 / 作答的。拒答不进分子也不进分母；</li>
 *   <li><b>作答率（覆盖率）</b> = 作答的 / <b>期望作答的</b>。
 *       期望拒答的那组<b>不进分母</b> —— 那组本来就不该有答案，
 *       算进"没答"里会把覆盖率人为压低；</li>
 *   <li><b>编造率</b> = 编造的 / 期望拒答的。</li>
 * </ul>
 *
 * <p><b>评测数据写入专用作用域，且每次评测前先清空</b> ——
 * 与 {@link MemoryRecallScorer} 同一套做法与同一套理由：
 * 残留记录会挤占检索名额，让实测值随运行次数下滑。
 */
public class MemoryAnswerScorer implements EvalExecutor.Scorer {

    /** 作答正确：说的正是期望的那条记忆。 */
    public static final String ANSWERED = "ANSWERED";

    /** 作答错误：说了另一条记忆。 */
    public static final String WRONG = "WRONG";

    /**
     * 编造：库里没有对应事实，系统却说了点什么。
     *
     * <p><b>这是本维度最严重的失败</b>，比"答错"还严重：
     * "答错"是说了库里有但不对的那条；"编造"是说了库里<b>根本没有</b>的事。
     * 用户听到后者时无从分辨真假 —— 信任一旦损失，
     * 记忆这个核心卖点就废了。
     */
    public static final String FABRICATED = "FABRICATED";

    /**
     * 如实拒答。
     *
     * <p><b>它不会被返回</b>：拒答在返回给执行器时被映射成
     * {@link EvalExecutor#NON_APPLICABLE} ——
     * 拒答是<b>正确行为</b>，既不算进准确率的分子，也不该算进分母。
     * 保留这个常量是为了让代码里的意图自解释：
     * 读代码的人看到"拒答"能立刻知道它为什么会被标记为不适用。
     */
    public static final String REFUSED = "REFUSED";

    /** 评测专用作用域的租户标识。与 {@link MemoryRecallScorer} 一致。 */
    public static final String EVAL_TENANT_ID = MemoryRecallScorer.EVAL_TENANT_ID;

    /** 评测专用作用域的主体标识。与 {@link MemoryRecallScorer} 一致。 */
    public static final String EVAL_OWNER_KEY = MemoryRecallScorer.EVAL_OWNER_KEY;

    /** 长期记忆存储。 */
    private final LongTermStore store;

    /** 作用域解析器。 */
    private final ScopeResolver resolver;

    /** 检索返回条数上限。 */
    private final int topK;

    /** 相关性准入策略。与生产回复链路用的是同一套判据。 */
    private final MemoryRelevancePolicy policy;

    /** 评测作用域。 */
    private final MemoryScope evalScope;

    /** 本轮实际作答（而非拒答）的样本数。 */
    private int answeredCount;

    /** 本轮参与判定的样本数。 */
    private int scoredCount;

    /** 本轮期望拒答的样本数（库里没有对应事实的那组）。 */
    private int refusalExpectedCount;

    /** 本轮期望作答的样本数（库里有对应事实的那组）。 */
    private int answerExpectedCount;

    /** 本轮在"期望拒答"的样本里**编造**（不拒答而是作答）的条数。 */
    private int fabricatedCount;

    /**
     * 构造记忆作答打分器。
     *
     * @param store    长期记忆存储
     * @param resolver 作用域解析器
     * @param topK     检索返回条数上限
     */
    public MemoryAnswerScorer(LongTermStore store, ScopeResolver resolver, int topK) {
        this(store, resolver, topK, MemoryRelevancePolicy.standard());
    }

    /**
     * 构造记忆作答打分器。
     *
     * @param store    长期记忆存储
     * @param resolver 作用域解析器
     * @param topK     检索返回条数上限
     * @param policy   相关性准入策略
     */
    public MemoryAnswerScorer(LongTermStore store, ScopeResolver resolver, int topK,
        MemoryRelevancePolicy policy) {

        this.store = store;
        this.resolver = resolver;
        this.topK = topK;
        this.policy = policy;
        this.evalScope = MemoryScope.of(EVAL_TENANT_ID, EVAL_OWNER_KEY);
    }

    /**
     * 返回评测作用域。
     *
     * @return 评测作用域
     */
    public MemoryScope evalScope() {
        return evalScope;
    }

    /**
     * 写入全部样本的记忆原文。
     *
     * <p>与 {@link MemoryRecallScorer#prepare} 是同一批数据、同一套清空逻辑。
     *
     * <p><b>期望拒答的样本不写入任何内容</b> ——
     * 那类样本的前提就是"库里没有这条记忆"，
     * 自己写一条进去就把前提破坏了，测出来的拒答率是假的。
     *
     * @param dataset 评测集
     * @return 实际写入的记忆原文条数
     */
    public int prepare(EvalDataset dataset) {
        List<EvalSample> samples = dataset.samplesOf(EvalDimension.MEMORY_ANSWER);
        Set<String> corpus = new LinkedHashSet<>();
        for (EvalSample sample : samples) {
            if (sample.expectsRefusal()) {
                continue;
            }
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

    /**
     * 返回本打分器可能产出的全部结果词。
     *
     * <p>评测集的期望值只有 {@code ANSWERED}，
     * 但打分器合法地会产出 {@code WRONG} 与拒答标记 ——
     * 不声明它们，执行器会把这两种结果误判成"打分器写错了"，
     * 从而在模型退化的那一刻反而跳过门禁判定。
     *
     * @return 结果词集合
     */
    @Override
    public java.util.Set<String> vocabulary() {
        return java.util.Set.of(
            ANSWERED, WRONG, FABRICATED, EvalExecutor.NON_APPLICABLE);
    }

    @Override
    public String score(EvalSample sample) {
        return resolver.withScopeResult(evalScope, () -> {
            List<ScoredMemoryRecord> candidates = searchScored(sample.input());

            OptionalAnswer answer = decide(candidates, sample);
            scoredCount++;
            if (answer.didAnswer()) {
                answeredCount++;
            }
            if (sample.expectsRefusal()) {
                refusalExpectedCount++;
                if (answer.didAnswer()) {
                    fabricatedCount++;
                }
            } else {
                answerExpectedCount++;
            }
            return answer.outcome();
        });
    }

    /**
     * 检索候选命中。
     *
     * <p>底层存储支持带得分检索时走得分路径（相关性准入需要它）；
     * 不支持时退化为普通检索，此时候选的得分标记为"未知"，
     * 准入策略会跳过相关性判据 —— <b>不会把"未知"伪装成"已知"</b>。
     *
     * @param query 查询文本
     * @return 候选命中
     */
    private List<ScoredMemoryRecord> searchScored(String query) {
        if (store instanceof ScoredMemorySearch scored) {
            return scored.searchScored(query, topK);
        }
        return store.search(query, topK).stream()
                .map(ScoredMemoryRecord::unscored)
                .toList();
    }

    /**
     * 判定本条样本的作答结果。
     *
     * <p><b>两类样本、两类判定</b>：
     * <ul>
     *   <li><b>期望拒答的样本</b>（库里没有对应事实）——
     *       系统若没有作答，是<b>正确行为</b>；
     *       系统若作答了，说明它<b>编造</b>了库里没有的事 ——
     *       这是本维度最严重的失败；</li>
     *   <li><b>期望作答的样本</b>（库里有对应事实）——
     *       系统作答且说的正是期望内容，是正确；
     *       说的是另一条，是答错；
     *       没作答，是漏答（覆盖率损失，不是编造）。</li>
     * </ul>
     *
     * @param candidates 候选命中
     * @param sample     评测样本
     * @return 判定结果
     */
    private OptionalAnswer decide(List<ScoredMemoryRecord> candidates, EvalSample sample) {
        String expectedContent = sample.expectedContentOrNull();

        if (candidates.isEmpty()) {
            return OptionalAnswer.refused();
        }
        var selected = policy.select(candidates);
        if (selected.isEmpty()) {
            // 没有通过相关性准入 —— 产品会如实说"没有记录"。
            return OptionalAnswer.refused();
        }

        MemoryRecord spoken = selected.get().record();
        if (expectedContent == null) {
            // 库里没有这条记忆 —— 任何作答都是编造。
            return OptionalAnswer.fabricated(spoken.content());
        }
        return spoken.content().equals(expectedContent)
                ? OptionalAnswer.correct()
                : OptionalAnswer.wrong(spoken.content());
    }

    /**
     * 返回作答率（覆盖率）。
     *
     * <p><b>口径</b>：<b>期望作答的样本</b>里，系统实际作答的比例。
     * 期望拒答的样本<b>不进分母</b> ——
     * 那组样本本来就不该有答案，把它们算进"没答"里，
     * 覆盖率会被人为压低（实测会从 76.9% 掉到 40%）。
     *
     * <p><b>为什么必须有这个数</b>：一个"永远拒答"的系统，
     * 作答准确率也是满分 —— 那样的机器人毫无用处。
     * 作答率保证"该答的时候答得出来"。
     *
     * @return 作答率；没有期望作答的样本时返回 0
     */
    public double answerRate() {
        if (answerExpectedCount == 0) {
            return 0.0;
        }
        return (double) answeredCount / answerExpectedCount;
    }

    /**
     * 返回本轮参与判定的样本数。
     *
     * @return 样本数
     */
    public int scoredCount() {
        return scoredCount;
    }

    /**
     * 返回本轮实际作答的样本数。
     *
     * @return 作答数
     */
    public int answeredCount() {
        return answeredCount;
    }

    /**
     * 返回本轮期望拒答的样本数。
     *
     * @return 期望拒答的样本数
     */
    public int refusalExpectedCount() {
        return refusalExpectedCount;
    }

    /**
     * 返回本轮期望作答的样本数。
     *
     * @return 期望作答的样本数
     */
    public int answerExpectedCount() {
        return answerExpectedCount;
    }

    /**
     * 返回本轮编造的条数。
     *
     * @return 编造条数
     */
    public int fabricatedCount() {
        return fabricatedCount;
    }

    /**
     * 返回编造率。
     *
     * <p><b>口径</b>：期望拒答的样本里，系统不拒答而是作答的比例。
     * 拒答的样本数越多，这个数越有意义；没有这类样本时返回 0
     * （而不是 1，否则在没有测到编造的场景下会误报）。
     *
     * @return 编造率；没有期望拒答的样本时返回 0
     */
    public double fabricationRate() {
        if (refusalExpectedCount == 0) {
            return 0.0;
        }
        return (double) fabricatedCount / refusalExpectedCount;
    }

    /**
     * 一条样本的作答判定。
     *
     * @param outcome  判定结果
     * @param didAnswer 是否真的作了答
     * @param spoken   实际说出的记忆内容
     */
    private record OptionalAnswer(String outcome, boolean didAnswer, String spoken) {

        static OptionalAnswer correct() {
            return new OptionalAnswer(ANSWERED, true, "");
        }

        static OptionalAnswer refused() {
            // 拒答是**正确行为**，不是失败 ——
            // 它既不算进准确率的分子，也不该算进分母。
            // 用 NON_APPLICABLE 把它标成"不适用"，由执行器从分母里剔除。
            return new OptionalAnswer(EvalExecutor.NON_APPLICABLE, false, "");
        }

        static OptionalAnswer wrong(String content) {
            return new OptionalAnswer(WRONG, true, content);
        }

        /**
         * 编造：库里没有这条记忆，系统却说了点什么。
         *
         * <p>这是本维度最严重的失败 ——
         * 用户听到了一句**看起来有依据、实则库里根本没有**的话。
         * 机器人一旦开始编造，用户就再也不能相信它的记忆。
         */
        static OptionalAnswer fabricated(String content) {
            return new OptionalAnswer(FABRICATED, true, content);
        }
    }
}
