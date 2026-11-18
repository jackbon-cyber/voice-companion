package com.company.bj.voice.cloud.memory.spi;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.company.bj.voice.cloud.memory.LongTermStore;
import com.company.bj.voice.cloud.memory.MemoryRecord;
import com.company.bj.voice.cloud.memory.MemoryScope;
import com.company.bj.voice.cloud.memory.ScopeResolver;
import io.agentscope.core.message.Msg;
import io.agentscope.core.message.MsgRole;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * {@link MemoryServiceAdapter} 的隔离性测试。
 *
 * <p>核心断言：<b>适配器不得成为作用域隔离的旁路</b>。
 * AgentScope 的记忆契约允许按作用域查询，本适配器<b>刻意不实现</b>这条路径 ——
 * 越权读取返回空，而不是抛异常，更不是返回别人的记忆。
 */
class MemoryServiceAdapterTest {

    /** 首个用户的作用域。 */
    private static final MemoryScope USER_ONE = MemoryScope.of("tenant-a", "user-1");

    /** 第二个用户的作用域。 */
    private static final MemoryScope USER_TWO = MemoryScope.of("tenant-a", "user-2");

    /**
     * 内存假存储：写入按当前作用域归属，读出时<b>不过滤</b>。
     *
     * <p>刻意模拟"底层实现有疏漏"这一真正需要上层兜底的情形 ——
     * 若假存储自己就过滤了作用域，测试就测不到适配器的兜底逻辑。
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
                "id-" + counter,
                content,
                weight,
                System.currentTimeMillis(),
                resolver.current(),
                false);
            records.add(record);
            return record;
        }

        @Override
        public Optional<MemoryRecord> find(String id) {
            return records.stream().filter(record -> record.id().equals(id)).findFirst();
        }

        @Override
        public List<MemoryRecord> search(String query, int topK) {
            return records.stream().limit(topK).toList();
        }

        @Override
        public List<MemoryRecord> list(int topK) {
            return records.stream().limit(topK).toList();
        }

        @Override
        public boolean forget(String id) {
            return records.removeIf(record -> record.id().equals(id));
        }

        @Override
        public List<MemoryRecord> archived(int topK) {
            return List.of();
        }

        @Override
        public int clearCurrentScope() {
            MemoryScope scope = resolver.current();
            int before = records.size();
            records.removeIf(record -> record.scope().equals(scope));
            return before - records.size();
        }

        @Override
        public Optional<MemoryRecord> consolidate(List<String> ids) {
            return Optional.empty();
        }
    }

    private static Msg userMessage(String text) {
        return Msg.builder()
                .role(MsgRole.USER)
                .textContent(text)
                .build();
    }

    @Test
    @DisplayName("同一作用域内写入的记忆可以被检索到")
    void shouldStoreAndRecallRecordWithinSameScope() {
        ScopeResolver resolver = new ScopeResolver();
        MemoryServiceAdapter adapter = new MemoryServiceAdapter(new InMemoryStore(resolver), resolver);

        resolver.withScope(USER_ONE, () -> adapter.record(List.of(userMessage("我叫李芳"))).block());
        String recalled = resolver.withScopeResult(USER_ONE, () -> adapter.retrieve(userMessage("我叫什么")).block());

        assertNotNull(recalled);
        assertTrue(recalled.contains("李芳"), "应召回本作用域写入的记忆，实际：" + recalled);
    }

    @Test
    @DisplayName("跨作用域检索必须返回空，不得返回他人记忆")
    void shouldNotRecallRecordAcrossScopes() {
        ScopeResolver resolver = new ScopeResolver();
        MemoryServiceAdapter adapter = new MemoryServiceAdapter(new InMemoryStore(resolver), resolver);

        resolver.withScope(USER_ONE, () -> adapter.record(List.of(userMessage("我叫李芳"))).block());
        String recalled = resolver.withScopeResult(USER_TWO, () -> adapter.retrieve(userMessage("我叫什么")).block());

        assertTrue(recalled == null || recalled.isBlank(), "跨作用域不得召回任何记忆，实际：" + recalled);
    }

    @Test
    @DisplayName("跨作用域写入的记录即使底层不过滤，也必须被拦下")
    void shouldBlockCrossScopeRecordsEvenWhenStoreDoesNotFilter() {
        ScopeResolver resolver = new ScopeResolver();
        MemoryServiceAdapter adapter = new MemoryServiceAdapter(new InMemoryStore(resolver), resolver);

        resolver.withScope(USER_ONE, () -> adapter.record(List.of(userMessage("我叫李芳"))).block());

        // 假存储的 search 不按作用域过滤，会把 user-1 的记录也返回 ——
        // 适配器必须把不属于当前作用域的记录剔除。
        String recalled = resolver.withScopeResult(USER_TWO, () -> adapter.retrieve(userMessage("我叫什么")).block());

        assertTrue(recalled == null || recalled.isBlank(), "必须拦下跨作用域记录，实际：" + recalled);
    }

    @Test
    @DisplayName("无活动作用域时拒绝操作，不得退化为默认作用域")
    void shouldRejectOperationWithoutActiveScope() {
        ScopeResolver resolver = new ScopeResolver();
        MemoryServiceAdapter adapter = new MemoryServiceAdapter(new InMemoryStore(resolver), resolver);

        assertThrows(IllegalStateException.class, () -> adapter.record(List.of(userMessage("我叫李芳"))).block());
        assertThrows(IllegalStateException.class, () -> adapter.retrieve(userMessage("我叫什么")).block());
    }

    @Test
    @DisplayName("作用域归属判定只放行当前作用域的未归档记录")
    void shouldAcceptOnlyCurrentScopeNonArchivedRecords() {
        ScopeResolver resolver = new ScopeResolver();
        MemoryServiceAdapter adapter = new MemoryServiceAdapter(new InMemoryStore(resolver), resolver);

        resolver.withScope(USER_ONE, () -> {
            adapter.record(List.of(userMessage("我叫李芳"))).block();
            // 同作用域、未归档 → 可见
            assertTrue(recalledContent(adapter, "我叫什么").contains("李芳"));
        });

        resolver.withScope(USER_TWO, () -> {
            // 异作用域 → 不可见
            assertEquals("", recalledContent(adapter, "我叫什么"));
        });
    }

    /** 取出适配器召回的文本内容，便于断言。 */
    private static String recalledContent(MemoryServiceAdapter adapter, String query) {
        String recalled = adapter.retrieve(userMessage(query)).block();
        return recalled == null ? "" : recalled;
    }
}
