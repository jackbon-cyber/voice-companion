package com.company.bj.voice.cloud.memory.companion;

import static org.assertj.core.api.Assertions.assertThat;

import com.company.bj.voice.cloud.memory.LongTermStore;
import com.company.bj.voice.cloud.memory.MemoryRecord;
import com.company.bj.voice.cloud.memory.MemoryScope;
import com.company.bj.voice.cloud.memory.ScopeResolver;
import com.company.bj.voice.cloud.memory.SessionOwnerRegistry;
import com.company.bj.voice.cloud.reply.MemoryGroundedReplyService;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * {@link SessionMemoryOrchestrator} 与 {@link MemoryGroundedReplyService} 的
 * 跨用户隔离测试。
 *
 * <p><b>核心断言</b>：用户 A 写入的记忆，在用户 B 的会话里<b>既召不回、
 * 也不会出现在回复的引用来源里</b>。
 *
 * <p>这里用的是<b>不过滤</b>的假存储 —— 它模拟"底层实现有疏漏"的最坏情况，
 * 证明隔离由上层强制施加，而不是碰巧由存储层实现正确。
 */
class SessionMemoryOrchestratorTest {

    /** 内存假存储：写入时归属当前作用域，读出时<b>不过滤</b>。 */
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
            MemoryRecord record = new MemoryRecord("id-" + counter, content, weight,
                    System.currentTimeMillis(), resolver.current(), false);
            records.add(record);
            return record;
        }

        @Override
        public Optional<MemoryRecord> find(String id) {
            return records.stream().filter(record -> record.id().equals(id)).findFirst();
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
        public List<MemoryRecord> search(String query, int topK) {
            return records.stream()
                    .filter(record -> matches(query, record.content()))
                    .limit(topK)
                    .toList();
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

    /** 作用域解析器。 */
    private ScopeResolver resolver;

    /** 会话归属注册表。 */
    private SessionOwnerRegistry ownerRegistry;

    /** 被测编排服务。 */
    private SessionMemoryOrchestrator orchestrator;

    /** 被测回复服务。 */
    private MemoryGroundedReplyService replyService;

    @BeforeEach
    void setUp() {
        resolver = new ScopeResolver();
        ownerRegistry = new SessionOwnerRegistry(MemoryScope.DEFAULT_TENANT_ID);
        CompanionMemoryClassifier classifier = new CompanionMemoryClassifier();
        LeakyStore leakyStore = new LeakyStore(resolver);
        ScopedCompanionMemoryStore store = new ScopedCompanionMemoryStore(leakyStore, resolver);
        orchestrator = new SessionMemoryOrchestrator(store, resolver, ownerRegistry, classifier,
                new MemoryUpdateService(store, FingerprintCalculator.lexical()));
        replyService = new MemoryGroundedReplyService(orchestrator);
    }

    @Test
    @DisplayName("会话开始后按用户标识解析作用域")
    void 会话开始后按用户标识解析作用域() {
        ownerRegistry.bind("session-a", "user-a");

        assertThat(ownerRegistry.scopeOf("session-a"))
                .isEqualTo(MemoryScope.of(MemoryScope.DEFAULT_TENANT_ID, "user-a"));
    }

    @Test
    @DisplayName("未登记用户标识时退化为缺省作用域")
    void 未登记用户标识时退化为缺省作用域() {
        // 未接入账号体系的设备仍应能正常对话，只是记忆不与他人共享。
        assertThat(ownerRegistry.scopeOf("session-unknown"))
                .isEqualTo(MemoryScope.defaultScope());
    }

    @Test
    @DisplayName("长期类内容被写入记忆")
    void 长期类内容被写入记忆() {
        ownerRegistry.bind("session-a", "user-a");

        MemoryUpdateService.UpdateOutcome outcome =
                orchestrator.remember("session-a", "我妈妈叫李芳");

        assertThat(outcome.status())
                .isEqualTo(MemoryUpdateService.UpdateOutcome.UpdateStatus.CREATED);
        assertThat(orchestrator.listForSession("session-a", 10)).hasSize(1);
    }

    @Test
    @DisplayName("一次性指令不写入长期记忆")
    void 一次性指令不写入长期记忆() {
        ownerRegistry.bind("session-a", "user-a");

        MemoryUpdateService.UpdateOutcome outcome =
                orchestrator.remember("session-a", "把音量调到五十");

        assertThat(outcome.status())
                .isEqualTo(MemoryUpdateService.UpdateOutcome.UpdateStatus.REJECTED);
        assertThat(orchestrator.listForSession("session-a", 10)).isEmpty();
    }

    @Test
    @DisplayName("用户B召不回用户A的记忆")
    void 用户B召不回用户A的记忆() {
        ownerRegistry.bind("session-a", "user-a");
        ownerRegistry.bind("session-b", "user-b");
        orchestrator.remember("session-a", "我妈妈叫李芳");

        List<MemoryRecord> recalled = orchestrator.recall("session-b", "李芳", 10);

        assertThat(recalled).isEmpty();
    }

    @Test
    @DisplayName("用户B的回复不引用用户A的记忆")
    void 用户B的回复不引用用户A的记忆() {
        ownerRegistry.bind("session-a", "user-a");
        ownerRegistry.bind("session-b", "user-b");
        orchestrator.remember("session-a", "我妈妈叫李芳");

        MemoryGroundedReplyService.GroundedReply reply =
                replyService.reply("session-b", "我妈妈叫什么");

        assertThat(reply.citations()).isEmpty();
        assertThat(reply.grounded()).isFalse();
        assertThat(reply.text()).doesNotContain("李芳");
    }

    @Test
    @DisplayName("用户A的回复引用自己的记忆")
    void 用户A的回复引用自己的记忆() {
        ownerRegistry.bind("session-a", "user-a");
        orchestrator.remember("session-a", "我妈妈叫李芳");

        MemoryGroundedReplyService.GroundedReply reply =
                replyService.reply("session-a", "我妈妈叫什么");

        assertThat(reply.citations()).hasSize(1);
        assertThat(reply.sources()).containsExactly("我妈妈叫李芳");
        assertThat(reply.text()).contains("李芳");
    }

    @Test
    @DisplayName("交替对话后用户仍只看到自己的记忆")
    void 交替对话后用户仍只看到自己的记忆() {
        ownerRegistry.bind("session-a", "user-a");
        ownerRegistry.bind("session-b", "user-b");

        orchestrator.remember("session-a", "我妈妈叫李芳");
        orchestrator.remember("session-b", "我妈妈叫王芳");

        MemoryGroundedReplyService.GroundedReply replyA =
                replyService.reply("session-a", "我妈妈叫什么");
        MemoryGroundedReplyService.GroundedReply replyB =
                replyService.reply("session-b", "我妈妈叫什么");

        assertThat(replyA.sources()).containsExactly("我妈妈叫李芳");
        assertThat(replyB.sources()).containsExactly("我妈妈叫王芳");
    }

    @Test
    @DisplayName("解绑后新会话不再继承旧用户的身份")
    void 解绑后新会话不再继承旧用户的身份() {
        ownerRegistry.bind("session-a", "user-a");
        orchestrator.remember("session-a", "我妈妈叫李芳");

        // 会话结束必须解绑：绑定残留会让下一个复用同一会话标识的会话
        // 继承前一个用户的身份，从而读到前一个用户的记忆。
        ownerRegistry.unbind("session-a");

        assertThat(orchestrator.recall("session-a", "李芳", 10)).isEmpty();
    }
}
