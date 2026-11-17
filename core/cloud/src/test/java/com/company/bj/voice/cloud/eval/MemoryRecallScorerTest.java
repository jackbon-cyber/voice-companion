package com.company.bj.voice.cloud.eval;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.company.bj.voice.cloud.memory.LongTermStore;
import com.company.bj.voice.cloud.memory.MemoryRecord;
import com.company.bj.voice.cloud.memory.MemoryScope;
import com.company.bj.voice.cloud.memory.ScopeResolver;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * {@link MemoryRecallScorer} 的隔离性与可复现性测试。
 *
 * <p>核心断言三条：
 * <ol>
 *   <li><b>评测记忆落在专用作用域</b>，不污染生产作用域；</li>
 *   <li><b>每次评测前清空评测作用域</b>，旧数据不挤占 topK 名额；</li>
 *   <li><b>检索不到时如实判失败</b>，不粉饰指标。</li>
 * </ol>
 */
class MemoryRecallScorerTest {

    /**
     * 内存假存储：按作用域分桶，检索按<b>语义近似</b>粗匹配，
     * 忠实还原"残留记录会挤占 topK 名额"这一真实故障模式。
     *
     * <p><b>为什么检索不用 {@code contains} 精确匹配</b>：
     * 记忆召回要测的是"用<b>另一种说法</b>问，能不能找回那条记忆"，
     * 而问句与记忆原文必然不同。精确匹配会让所有"不同表述"的样本
     * 必然召回失败，测到的是字符串相等而不是打分器的真实职责。
     * 这里用"共享任一实词即视为语义相关"来近似真实嵌入检索的行为。
     */
    private static final class InMemoryStore implements LongTermStore {
        private final List<MemoryRecord> records = new ArrayList<>();
        private final ScopeResolver resolver;
        private int counter;

        InMemoryStore(ScopeResolver resolver) {
            this.resolver = resolver;
        }

        @Override
        public MemoryRecord remember(String content) {
            return remember(content, 1.0);
        }

        @Override
        public MemoryRecord remember(String content, double weight) {
            counter++;
            MemoryRecord record = new MemoryRecord(
                "id-" + counter, content, weight, System.currentTimeMillis(),
                resolver.current(), false);
            records.add(record);
            return record;
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
         * <p>按双字滑窗切分："我奶奶家在哪里"切出"我奶"、"奶奶"、"奶家"、
         * "家在"、"在哪"、"哪里"。双字窗口让"奶奶家"与"奶奶住在苏州"
         * 共享"奶奶"这个实词，从而体现语义相关性。
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
    private final InMemoryStore store = new InMemoryStore(resolver);

    /** 打分器。 */
    private final MemoryRecallScorer scorer = new MemoryRecallScorer(store, resolver, 5);

    /**
     * 构造一条记忆召回样本。
     *
     * @param input    问句
     * @param expected 期望结果
     * @param corpus   记忆原文
     * @return 样本
     */
    private static EvalSample sample(String input, String expected, String corpus) {
        return EvalSample.withCorpus(EvalDimension.MEMORY_RECALL, input, expected, corpus);
    }

    @Test
    @DisplayName("评测记忆写入专用作用域，不污染生产作用域")
    void 评测记忆写入专用作用域不污染生产作用域() {
        EvalDataset datasetUnderTest = new EvalDataset(List.of(
            sample("我奶奶家在哪里", "RECALLED", "我奶奶住在苏州")));

        scorer.prepare(datasetUnderTest);

        assertEquals(MemoryScope.of("evaluation", "evaluation"), scorer.evalScope(),
            "评测必须使用专用作用域");
        assertEquals(1, store.records.size());
        assertEquals(MemoryScope.of("evaluation", "evaluation"), store.records.get(0).scope(),
            "评测记忆必须落在评测作用域");
    }

    @Test
    @DisplayName("评测前清空评测作用域，旧数据不挤占 topK 名额")
    void 评测前清空评测作用域旧数据不挤占TopK名额() {
        EvalDataset datasetUnderTest = new EvalDataset(List.of(
            sample("我奶奶家在哪里", "RECALLED", "我奶奶住在苏州"),
            sample("我养了几只小动物", "RECALLED", "我养了三只仓鼠")));

        // 第一轮：正常写入
        scorer.prepare(datasetUnderTest);
        assertEquals(2, store.records.size());

        // 第二轮：prepare 必须先清空再写入，记录数不增长
        scorer.prepare(datasetUnderTest);
        assertEquals(2, store.records.size(),
            "重复评测不得累积重复记录，否则实测值会随运行次数下滑");
    }

    @Test
    @DisplayName("清空只影响评测作用域，不动其他作用域的记录")
    void 清空只影响评测作用域不动其他作用域的记录() {
        resolver.withScope(MemoryScope.of("default", "default"), () -> store.remember("生产记忆"));
        scorer.prepare(new EvalDataset(List.of(
            sample("我奶奶家在哪里", "RECALLED", "我奶奶住在苏州"))));

        assertEquals(2, store.records.size(), "生产作用域的记录必须保留");
        assertTrue(store.records.stream()
            .anyMatch(record -> record.content().equals("生产记忆")),
            "清空评测作用域不得波及生产作用域");
    }

    @Test
    @DisplayName("问句与记忆原文不同表述时仍能召回")
    void 问句与记忆原文不同表述时仍能召回() {
        EvalDataset datasetUnderTest = new EvalDataset(List.of(
            sample("我奶奶家在哪里", "RECALLED", "我奶奶住在苏州")));

        scorer.prepare(datasetUnderTest);
        EvalSample one = datasetUnderTest.samplesOf(EvalDimension.MEMORY_RECALL).get(0);

        assertEquals("RECALLED", scorer.score(one));
    }

    @Test
    @DisplayName("检索不到时如实判失败，不粉饰指标")
    void 检索不到时如实判失败不粉饰指标() {
        EvalDataset datasetUnderTest = new EvalDataset(List.of(
            sample("我奶奶家在哪里", "RECALLED", "我奶奶住在苏州")));

        scorer.prepare(datasetUnderTest);

        // 问句与记忆原文毫无关联，检索必然落空
        EvalSample unrelated = sample("完全无关的问句", "RECALLED", "我奶奶住在苏州");

        assertEquals("MISSED", scorer.score(unrelated));
    }

    @Test
    @DisplayName("评测作用域与生产作用域互不相通")
    void 评测作用域与生产作用域互不相通() {
        assertNotEquals(MemoryScope.defaultScope(), scorer.evalScope(),
            "评测作用域不得与生产缺省作用域相同");
    }
}
