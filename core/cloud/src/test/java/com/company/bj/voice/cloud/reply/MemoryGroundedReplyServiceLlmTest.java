package com.company.bj.voice.cloud.reply;

import static org.assertj.core.api.Assertions.assertThat;

import com.company.bj.voice.cloud.memory.LongTermStore;
import com.company.bj.voice.cloud.memory.MemoryRecord;
import com.company.bj.voice.cloud.memory.MemoryScope;
import com.company.bj.voice.cloud.memory.ScopeResolver;
import com.company.bj.voice.cloud.memory.SessionOwnerRegistry;
import com.company.bj.voice.cloud.memory.companion.CompanionMemoryClassifier;
import com.company.bj.voice.cloud.memory.companion.FingerprintCalculator;
import com.company.bj.voice.cloud.memory.companion.MemoryRelevancePolicy;
import com.company.bj.voice.cloud.memory.companion.MemoryUpdateService;
import com.company.bj.voice.cloud.memory.companion.ScopedCompanionMemoryStore;
import com.company.bj.voice.cloud.memory.companion.SessionMemoryOrchestrator;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 接入大模型后，记忆隔离与引用来源仍然成立的测试。
 *
 * <p><b>为什么这组测试不可省略</b>：端到端的跨用户隔离断言依赖
 * {@code citations} 字段。如果引用来源改由模型生成，
 * 隔离断言就失去了机器可判定的依据 ——
 * 所以"引用来源由代码填充"必须被测试钉死，不能只是写在注释里。
 */
class MemoryGroundedReplyServiceLlmTest {

    /** 内存假存储：写入时归属当前作用域，读出时不过滤（模拟底层有疏漏）。 */
    private static final class LeakyStore implements LongTermStore {
        private final List<MemoryRecord> records = new ArrayList<>();
        private final ScopeResolver resolver;
        private int counter;

        LeakyStore(ScopeResolver resolver) {
            this.resolver = resolver;
        }

        @Override
        public MemoryRecord remember(String content) {
            return remember(content, 1.0);
        }

        @Override
        public MemoryRecord remember(String content, double weight) {
            counter++;
            MemoryScope scope = resolver.current();
            MemoryRecord record = new MemoryRecord(
                "id-" + counter, content, weight, System.currentTimeMillis(), scope, false);
            records.add(record);
            return record;
        }

        @Override
        public Optional<MemoryRecord> find(String id) {
            return records.stream().filter(r -> r.id().equals(id)).findFirst();
        }

        @Override
        public List<MemoryRecord> search(String query, int topK) {
            return records.stream().filter(r -> matches(query, r.content())).limit(topK).toList();
        }

        /**
         * 用二元组重合度判断是否命中。
         *
         * <p>为什么不用 {@code content.contains(query)}：真实存储走的是**语义**检索，
         * 查询"我妈妈叫什么"应当命中"我妈妈叫李芳"。
         * 若假存储用严格包含，这两者匹配不上 ——
         * 测试就会因为假实现的简化而失败，而不是因为被测逻辑有错。
         *
         * @param query 查询文本
         * @param content 记录正文
         * @return 命中返回 {@code true}
         */
        private static boolean matches(String query, String content) {
            if (query == null || query.isBlank() || content == null) {
                return false;
            }
            if (content.contains(query)) {
                return true;
            }
            return bigrams(query).stream().anyMatch(content::contains);
        }

        /**
         * 取出文本的全部相邻二字组。
         *
         * @param text 文本
         * @return 二字组集合
         */
        private static java.util.Set<String> bigrams(String text) {
            java.util.Set<String> grams = new java.util.HashSet<>();
            for (int index = 0; index + 1 < text.length(); index++) {
                grams.add(text.substring(index, index + 2));
            }
            return grams;
        }

        @Override
        public List<MemoryRecord> list(int topK) {
            return records.stream().limit(topK).toList();
        }

        @Override
        public boolean forget(String id) {
            return true;
        }

        @Override
        public List<MemoryRecord> archived(int topK) {
            return List.of();
        }

        @Override
        public int clearCurrentScope() {
            int size = records.size();
            records.clear();
            return size;
        }

        @Override
        public Optional<MemoryRecord> consolidate(List<String> ids) {
            return Optional.empty();
        }
    }

    /** 措辞生成器：模拟大模型，**故意不返回记忆原文**，并返回自己的引用标识。 */
    private static final class PretendLlmPhrasing implements ReplyPhrasing {
        @Override
        public String phrase(String memoryContent) {
            // 模拟大模型：改写措辞，并试图夹带一个"自己编的引用"。
            return "这个我记得呀，是" + memoryContent + "哦。（模型自称引用 memory-fake-999）";
        }
    }

    /** 措辞生成器：模拟大模型完全不可用。 */
    private static final class BrokenLlmPhrasing implements ReplyPhrasing {
        @Override
        public String phrase(String memoryContent) {
            return "";
        }
    }

    /** 作用域解析器。 */
    private ScopeResolver resolver;

    /** 会话归属注册表。 */
    private SessionOwnerRegistry ownerRegistry;

    /** 被测编排服务。 */
    private SessionMemoryOrchestrator orchestrator;

    /**
     * 构造使用指定措辞生成器的回复服务。
     *
     * @param phrasing 措辞生成器
     * @return 回复服务
     */
    private MemoryGroundedReplyService replyService(ReplyPhrasing phrasing) {
        return new MemoryGroundedReplyService(
                orchestrator, MemoryRelevancePolicy.standard(), phrasing);
    }

    /**
     * 初始化编排链路。
     */
    @BeforeEach
    void setUp() {
        resolver = new ScopeResolver();
        ownerRegistry = new SessionOwnerRegistry(MemoryScope.DEFAULT_TENANT_ID);
        LeakyStore leakyStore = new LeakyStore(resolver);
        ScopedCompanionMemoryStore store = new ScopedCompanionMemoryStore(leakyStore, resolver);
        orchestrator = new SessionMemoryOrchestrator(store, resolver, ownerRegistry,
                new CompanionMemoryClassifier(),
                new MemoryUpdateService(store, FingerprintCalculator.lexical()));
        ownerRegistry.bind("session-a", "user-a");
        ownerRegistry.bind("session-b", "user-b");
    }

    @Test
    @DisplayName("大模型改写措辞后，引用来源仍只有代码选中的那一条")
    void 大模型改写措辞后引用来源仍由代码决定() {
        orchestrator.remember("session-a", "我妈妈叫李芳");

        MemoryGroundedReplyService.GroundedReply reply =
                replyService(new PretendLlmPhrasing()).reply("session-a", "我妈妈叫什么");

        assertThat(reply.text()).contains("李芳");
        assertThat(reply.citations()).hasSize(1);
        // 关键断言：模型自称的引用标识不得进入协议字段。
        assertThat(reply.citations()).doesNotContain("memory-fake-999");
        assertThat(reply.sources()).containsExactly("我妈妈叫李芳");
    }

    @Test
    @DisplayName("大模型改写措辞后，跨用户仍然不泄漏")
    void 大模型改写措辞后跨用户不泄漏() {
        orchestrator.remember("session-a", "我妈妈叫李芳");

        MemoryGroundedReplyService.GroundedReply reply =
                replyService(new PretendLlmPhrasing()).reply("session-b", "我妈妈叫什么");

        assertThat(reply.citations()).isEmpty();
        assertThat(reply.grounded()).isFalse();
        assertThat(reply.text()).doesNotContain("李芳");
    }

    @Test
    @DisplayName("大模型不可用时退回模板，仍产出可用回复")
    void 大模型不可用时退回模板() {
        orchestrator.remember("session-a", "我妈妈叫李芳");

        MemoryGroundedReplyService.GroundedReply reply =
                replyService(new BrokenLlmPhrasing()).reply("session-a", "我妈妈叫什么");

        assertThat(reply.text()).contains("李芳");
        assertThat(reply.text()).contains("我记得");
        assertThat(reply.citations()).hasSize(1);
    }

    @Test
    @DisplayName("模板路径的回复正文与历史一致，不因接入大模型而改变")
    void 模板路径回复正文不变() {
        orchestrator.remember("session-a", "我妈妈叫李芳");

        MemoryGroundedReplyService.GroundedReply reply =
                replyService(new TemplateReplyPhrasing()).reply("session-a", "我妈妈叫什么");

        assertThat(reply.text()).isEqualTo("我记得，我妈妈叫李芳");
    }
}
