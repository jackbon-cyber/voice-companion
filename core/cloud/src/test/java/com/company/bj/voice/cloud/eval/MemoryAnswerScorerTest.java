package com.company.bj.voice.cloud.eval;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.company.bj.voice.cloud.memory.LongTermStore;
import com.company.bj.voice.cloud.memory.MemoryRecord;
import com.company.bj.voice.cloud.memory.MemoryScope;
import com.company.bj.voice.cloud.memory.ScopeResolver;
import com.company.bj.voice.cloud.memory.ScoredMemoryRecord;
import com.company.bj.voice.cloud.memory.ScoredMemorySearch;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * {@link MemoryAnswerScorer} 的打分行为测试。
 *
 * <p>核心断言六条：
 * <ol>
 *   <li><b>排第一的那条就是期望的</b> → 判 {@code ANSWERED}；</li>
 *   <li><b>排第一的那条是另一条记忆</b> → 判 {@code WRONG}（答非所问）；</li>
 *   <li><b>库里没有对应事实却作答了</b> → 判 {@code FABRICATED}（最严重）；</li>
 *   <li><b>库里没有对应事实且拒答</b> → 判不适用，<b>不算失败</b>；</li>
 *   <li><b>作答率只以"期望作答"的样本为分母</b>，
 *       否则期望拒答的那组会把覆盖率人为压低；</li>
 *   <li><b>编造率以"期望拒答"的样本为分母</b>。</li>
 * </ol>
 */
class MemoryAnswerScorerTest {

    /**
     * 内存假存储：按作用域分桶，检索按<b>实词命中</b>粗匹配。
     *
     * <p><b>为什么不模拟语义检索</b>：本测试要验证的是打分器的<b>判定口径</b>，
     * 而不是检索质量。检索质量由真实嵌入服务在评测里度量。
     * 这里用可控的命中规则，把"排第一的那条"精确指定，
     * 让每条断言都指向唯一的原因。
     */
    private static final class OrderedStore implements LongTermStore, ScoredMemorySearch {
        private final List<MemoryRecord> records = new ArrayList<>();
        private final ScopeResolver resolver;
        private int counter;

        OrderedStore(ScopeResolver resolver) {
            this.resolver = resolver;
        }

        @Override
        public MemoryRecord remember(String content) {
            counter++;
            MemoryRecord record = new MemoryRecord(
                "id-" + counter, content, 1.0, counter,
                resolver.current(), false);
            records.add(record);
            return record;
        }

        @Override
        public MemoryRecord remember(String content, double weight) {
            return remember(content);
        }

        @Override
        public Optional<MemoryRecord> find(String id) {
            return records.stream().filter(record -> record.id().equals(id)).findFirst();
        }

        @Override
        public List<MemoryRecord> search(String query, int topK) {
            List<String> queryTokens = tokenize(query);
            List<MemoryRecord> hits = new ArrayList<>();
            for (MemoryRecord record : records) {
                if (!record.scope().equals(resolver.current())) {
                    continue;
                }
                if (sharesToken(queryTokens, record.content())) {
                    hits.add(record);
                }
            }
            return hits.size() > topK ? hits.subList(0, topK) : hits;
        }

        @Override
        public List<ScoredMemoryRecord> searchScored(String query, int topK) {
            List<ScoredMemoryRecord> scored = new ArrayList<>();
            for (MemoryRecord record : search(query, topK)) {
                scored.add(new ScoredMemoryRecord(record, 0.90));
            }
            return scored;
        }

        /**
         * 判定查询与内容是否共享至少一个实词。
         *
         * @param queryTokens 查询切出的实词
         * @param content     待匹配的内容
         * @return 共享实词返回 {@code true}
         */
        private static boolean sharesToken(List<String> queryTokens, String content) {
            for (String token : queryTokens) {
                if (content.contains(token)) {
                    return true;
                }
            }
            return false;
        }

        /**
         * 把中文句子切成实词。
         *
         * <p>按双字滑窗切分，"我最喜欢吃什么"切出"我最"、"喜欢"、
         * "欢吃"、"吃什"、"什么"。"我爱"这个窗口
         * 让"我最爱吃酸菜鱼"与"我最喜欢吃红烧肉"同时命中，
         * 从而能构造出"排第一的那条不是期望值"的场景。
         *
         * @param text 待切分的文本
         * @return 实词列表
         */
        private static List<String> tokenize(String text) {
            List<String> tokens = new ArrayList<>();
            if (text == null || text.length() < 2) {
                return tokens;
            }
            for (int index = 0; index + 2 <= text.length(); index++) {
                tokens.add(text.substring(index, index + 2));
            }
            return tokens;
        }

        @Override
        public List<MemoryRecord> list(int topK) {
            return records.stream().limit(topK).toList();
        }

        @Override
        public boolean forget(String id) {
            return false;
        }

        @Override
        public List<MemoryRecord> archived(int topK) {
            return List.of();
        }

        @Override
        public int clearCurrentScope() {
            int before = records.size();
            records.removeIf(record -> record.scope().equals(resolver.current()));
            return before - records.size();
        }

        @Override
        public Optional<MemoryRecord> consolidate(List<String> ids) {
            return Optional.empty();
        }
    }

    /** 作用域解析器。 */
    private final ScopeResolver resolver = new ScopeResolver();

    /** 底层假存储。 */
    private final OrderedStore store = new OrderedStore(resolver);

    /** 打分器。 */
    private final MemoryAnswerScorer scorer = new MemoryAnswerScorer(store, resolver, 5);

    /**
     * 构造一条"期望作答"的样本。
     *
     * @param input    问句
     * @param expected 期望结果
     * @param corpus   记忆原文
     * @return 样本
     */
    private static EvalSample sample(String input, String expected, String corpus) {
        return EvalSample.withCorpus(EvalDimension.MEMORY_ANSWER, input, expected, corpus);
    }

    /**
     * 构造一条"期望拒答"的样本。
     *
     * @param input    问句
     * @param expected 期望结果
     * @return 样本
     */
    private static EvalSample refusalSample(String input, String expected) {
        return EvalSample.expectingRefusal(EvalDimension.MEMORY_ANSWER, input, expected);
    }

    @Test
    @DisplayName("排第一的正是期望的记忆时判作答正确")
    void 排第一的正是期望的记忆时判作答正确() {
        EvalDataset datasetUnderTest = new EvalDataset(List.of(
            sample("我奶奶家在哪里", "ANSWERED", "我奶奶住在苏州")));

        scorer.prepare(datasetUnderTest);
        EvalSample one = datasetUnderTest.samplesOf(EvalDimension.MEMORY_ANSWER).get(0);

        assertEquals("ANSWERED", scorer.score(one));
    }

    @Test
    @DisplayName("排第一的是另一条记忆时判作答错误")
    void 排第一的是另一条记忆时判作答错误() {
        EvalDataset datasetUnderTest = new EvalDataset(List.of(
            sample("我奶奶家在哪里", "ANSWERED", "我奶奶住在苏州")));

        scorer.prepare(datasetUnderTest);
        // 语料里先写入的是另一条记忆，它会排在检索结果第一位。
        EvalSample mismatched = sample("我奶奶家在哪里", "ANSWERED", "我奶奶住在杭州");

        assertEquals("WRONG", scorer.score(mismatched),
            "说错记忆内容必须如实判失败，不能粉饰成作答正确");
    }

    @Test
    @DisplayName("库里没有对应事实却作答了，判为编造")
    void 库里没有对应事实却作答了判为编造() {
        EvalDataset datasetUnderTest = new EvalDataset(List.of(
            sample("我奶奶家在哪里", "ANSWERED", "我奶奶住在苏州")));

        scorer.prepare(datasetUnderTest);
        // 期望拒答的样本，但库里那条记忆会被问句命中 —— 系统若作答就是编造。
        EvalSample expectsRefusal = refusalSample("我奶奶家在哪里", "REFUSED");

        assertEquals(MemoryAnswerScorer.FABRICATED, scorer.score(expectsRefusal),
            "库里没有的事被说出口就是编造，这是本维度最严重的失败");
    }

    @Test
    @DisplayName("库里没有对应事实且如实拒答，判为不适用而不是失败")
    void 库里没有对应事实且如实拒答判为不适用而不是失败() {
        EvalDataset datasetUnderTest = new EvalDataset(List.of(
            sample("我奶奶家在哪里", "ANSWERED", "我奶奶住在苏州")));

        scorer.prepare(datasetUnderTest);
        EvalSample unrelated = refusalSample("完全无关的问句", "REFUSED");

        assertEquals(EvalExecutor.NON_APPLICABLE, scorer.score(unrelated),
            "拒答是正确行为，必须被标为不适用而不是失败");
    }

    @Test
    @DisplayName("作答率只以期望作答的样本为分母")
    void 作答率只以期望作答的样本为分母() {
        EvalDataset datasetUnderTest = new EvalDataset(List.of(
            sample("我奶奶家在哪里", "ANSWERED", "我奶奶住在苏州"),
            refusalSample("完全无关的问句", "REFUSED")));

        scorer.prepare(datasetUnderTest);
        scorer.score(datasetUnderTest.samplesOf(EvalDimension.MEMORY_ANSWER).get(0));
        scorer.score(datasetUnderTest.samplesOf(EvalDimension.MEMORY_ANSWER).get(1));

        assertEquals(2, scorer.scoredCount());
        assertEquals(1, scorer.answerExpectedCount());
        assertEquals(1, scorer.refusalExpectedCount());
        assertEquals(1, scorer.answeredCount());
        assertEquals(1.0, scorer.answerRate(), 0.0001,
            "期望拒答的样本不进覆盖率分母，否则覆盖率会被人为压低");
    }

    @Test
    @DisplayName("编造率以期望拒答的样本为分母")
    void 编造率以期望拒答的样本为分母() {
        EvalDataset datasetUnderTest = new EvalDataset(List.of(
            sample("我奶奶家在哪里", "ANSWERED", "我奶奶住在苏州"),
            refusalSample("我奶奶家在哪里", "REFUSED"),
            refusalSample("完全无关的问句", "REFUSED")));

        scorer.prepare(datasetUnderTest);
        scorer.score(datasetUnderTest.samplesOf(EvalDimension.MEMORY_ANSWER).get(0));
        scorer.score(datasetUnderTest.samplesOf(EvalDimension.MEMORY_ANSWER).get(1));
        scorer.score(datasetUnderTest.samplesOf(EvalDimension.MEMORY_ANSWER).get(2));

        assertEquals(2, scorer.refusalExpectedCount());
        assertEquals(1, scorer.fabricatedCount());
        assertEquals(0.5, scorer.fabricationRate(), 0.0001);
    }

    @Test
    @DisplayName("评测记忆写入专用作用域，不污染生产作用域")
    void 评测记忆写入专用作用域不污染生产作用域() {
        EvalDataset datasetUnderTest = new EvalDataset(List.of(
            sample("我奶奶家在哪里", "ANSWERED", "我奶奶住在苏州")));

        scorer.prepare(datasetUnderTest);

        assertEquals(MemoryScope.of("evaluation", "evaluation"), scorer.evalScope(),
            "评测必须使用专用作用域");
        assertTrue(store.records.stream()
            .allMatch(record -> record.scope().equals(MemoryScope.of("evaluation", "evaluation"))),
            "评测记忆必须落在评测作用域");
    }

    @Test
    @DisplayName("期望拒答的样本不写入记忆库，否则前提被破坏")
    void 期望拒答的样本不写入记忆库否则前提被破坏() {
        EvalDataset datasetUnderTest = new EvalDataset(List.of(
            sample("我奶奶家在哪里", "ANSWERED", "我奶奶住在苏州"),
            refusalSample("我养的小狗叫什么名字", "REFUSED")));

        scorer.prepare(datasetUnderTest);

        assertEquals(1, store.records.size(),
            "期望拒答的样本若写入了记忆库，'库里没有答案'的前提就被破坏了");
    }

    @Test
    @DisplayName("重复评测不累积记录，实测值可复现")
    void 重复评测不累积记录实测值可复现() {
        EvalDataset datasetUnderTest = new EvalDataset(List.of(
            sample("我奶奶家在哪里", "ANSWERED", "我奶奶住在苏州"),
            sample("我养了几只小动物", "ANSWERED", "我养了三只仓鼠")));

        scorer.prepare(datasetUnderTest);
        assertEquals(2, store.records.size());

        scorer.prepare(datasetUnderTest);
        assertEquals(2, store.records.size(),
            "重复评测不得累积重复记录，否则实测值会随运行次数下滑");
    }

    @Test
    @DisplayName("答错时不会被误判成打分器词汇不一致")
    void 答错时不会被误判成打分器词汇不一致() {
        // 两条样本的期望记忆原文不同，但记忆原文共享同一个主体前缀，
        // 相关性准入的同主体去重会只保留最新那条 —— 于是第一条必然答错。
        EvalDataset datasetUnderTest = new EvalDataset(List.of(
            sample("我奶奶家在哪里", "ANSWERED", "我奶奶住在苏州"),
            sample("我奶奶家在哪里", "ANSWERED", "我奶奶住在杭州")));

        scorer.prepare(datasetUnderTest);

        EvalExecutor executor = new EvalExecutor(datasetUnderTest);
        EvalExecutor.DimensionResult result = executor.evaluate(
            EvalDimension.MEMORY_ANSWER, scorer);

        // 词汇不一致时返回的是"无样本"结果：样本数为 0、失败明细为空。
        // 这里断言的是**它没有**落进那个分支 —— 答错是指标不达标，不是打分器写错了。
        assertEquals(2, result.sampleSize(), "答错不得被误判成词汇不一致");
        assertEquals(1, result.failures().size(), "答错必须如实记入失败明细");
    }

    @Test
    @DisplayName("全部答错时门禁判定为不通过，绝不绕过门禁")
    void 全部答错时门禁判定为不通过绝不绕过门禁() {
        // 用一个只会答错的打分器直接验证执行器的门禁行为。
        //
        // 之所以不用 MemoryAnswerScorer：它带相关性准入，
        // 会把一部分答错转成拒答，测出来的就不是"纯答错"了。
        List<EvalSample> samples = new ArrayList<>();
        for (int index = 0; index < 12; index++) {
            samples.add(sample("问句" + index, "ANSWERED", "记忆" + index));
        }
        EvalDataset datasetUnderTest = new EvalDataset(samples);

        EvalExecutor executor = new EvalExecutor(datasetUnderTest);
        EvalExecutor.DimensionResult result = executor.evaluate(
            EvalDimension.MEMORY_ANSWER, new AlwaysWrongScorer());

        assertNotNull(result.passed(), "样本数足够时必须参与门禁判定");
        assertEquals(Boolean.FALSE, result.passed(),
            "全部答错时门禁必须判定为不通过，绝不能因为词汇不一致而跳过判定");
        assertEquals(12, result.failures().size());
        assertEquals(0.0, result.rate(), 0.0001);
    }

    @Test
    @DisplayName("打分器未声明词汇时，全部答错会被识别为词汇不一致")
    void 打分器未声明词汇时全部答错会被识别为词汇不一致() {
        List<EvalSample> samples = new ArrayList<>();
        for (int index = 0; index < 12; index++) {
            samples.add(sample("问句" + index, "ANSWERED", "记忆" + index));
        }
        EvalDataset datasetUnderTest = new EvalDataset(samples);

        EvalExecutor executor = new EvalExecutor(datasetUnderTest);
        EvalExecutor.DimensionResult result = executor.evaluate(
            EvalDimension.MEMORY_ANSWER, sample -> "WRONG");

        // 未声明词汇的打分器返回了期望值里没有出现的词 ——
        // 这确实可能是打分器写错了，执行器如实标记"不可信"。
        // 对比上面那条：声明了词汇的打分器则能给出真实的失败判定。
        assertEquals(0, result.sampleSize());
        assertTrue(result.conclusion().contains("不可信"), result.conclusion());
    }

    /**
     * 只会答错的打分器。
     *
     * <p>它<b>声明了</b>自己的词汇表 —— 这正是关键：
     * 声明之后，"全部答错"会被判成"指标不达标"，
     * 而不会被误判成"打分器写错了、不参与门禁判定"。
     */
    private static final class AlwaysWrongScorer implements EvalExecutor.Scorer {

        @Override
        public String score(EvalSample sample) {
            return MemoryAnswerScorer.WRONG;
        }

        @Override
        public java.util.Set<String> vocabulary() {
            return java.util.Set.of(MemoryAnswerScorer.WRONG);
        }
    }
}
