package com.company.bj.voice.cloud.memory.companion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
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
 * {@link ScopedCompanionMemoryStore} 的隔离性测试。
 *
 * <p>核心断言：<b>越权查询返回空</b>，且<b>无活动作用域时拒绝操作</b>。
 */
class ScopedCompanionMemoryStoreTest {

    /** 候选作用域，用于构造跨作用域的越权场景。 */
    private static final List<MemoryScope> SCOPES = List.of(
        MemoryScope.of("tenant-a", "user-1"),
        MemoryScope.of("tenant-b", "user-2"));

    /** 内存假存储：写入时归属当前作用域，读出时<b>不过滤</b>（模拟底层实现有疏漏）。 */
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
            MemoryScope scope = resolver.current();
            MemoryRecord record = new MemoryRecord(
                "id-" + counter, content, weight, System.currentTimeMillis(), scope, false);
            records.add(record);
            return record;
        }

        @Override
        public Optional<MemoryRecord> find(String id) {
            return records.stream().filter(record -> record.id().equals(id)).findFirst();
        }

        @Override
        public List<MemoryRecord> search(String query, int topK) {
            return records.stream()
                .filter(record -> record.content().contains(query))
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

        /**
         * 直接塞入一条指定作用域的记录，模拟底层实现的疏漏。
         *
         * @param content 记录内容
         * @param scope   记录归属的作用域
         * @return 写入的记录
         */
        MemoryRecord inject(String content, MemoryScope scope) {
            counter++;
            MemoryRecord record = new MemoryRecord(
                "id-" + counter, content, 1.0, System.currentTimeMillis(), scope, false);
            records.add(record);
            return record;
        }
    }

    /** 作用域解析器。 */
    private final ScopeResolver resolver = new ScopeResolver();

    /** 底层假存储。 */
    private final InMemoryStore delegate = new InMemoryStore(resolver);

    /** 被测存储。 */
    private final ScopedCompanionMemoryStore store =
        new ScopedCompanionMemoryStore(delegate, resolver);

    @Test
    @DisplayName("无活动作用域时拒绝写入")
    void 无活动作用域时拒绝写入() {
        assertThrows(IllegalStateException.class, () -> store.remember("我妈妈叫李芳"));
    }

    @Test
    @DisplayName("无活动作用域时拒绝检索")
    void 无活动作用域时拒绝检索() {
        assertThrows(IllegalStateException.class, () -> store.search("李芳", 10));
    }

    @Test
    @DisplayName("越权查询返回空")
    void 越权查询返回空() {
        resolver.withScope(MemoryScope.of("tenant-a", "user-1"), () -> {
            store.remember("记忆甲");
            store.remember("记忆乙");

            // 底层存储故意塞进一条属于另一个作用域的记录，
            // 模拟"实现有疏漏"的情形 —— 上层必须把它挡掉。
            delegate.inject("记忆丙", MemoryScope.of("tenant-b", "user-2"));

            List<MemoryRecord> found = store.search("记忆", 10);

            assertTrue(found.stream()
                .allMatch(record -> record.scope().equals(MemoryScope.of("tenant-a", "user-1"))),
                "检索结果必须全部属于当前作用域");
            assertEquals(2, found.size(), "跨作用域的记录必须被过滤掉");
        });
    }

    @Test
    @DisplayName("按标识读取越权记录返回空")
    void 按标识读取越权记录返回空() {
        MemoryRecord foreign = delegate.inject("他人记忆", MemoryScope.of("tenant-b", "user-2"));

        resolver.withScope(MemoryScope.of("tenant-a", "user-1"),
            () -> assertTrue(store.find(foreign.id()).isEmpty(), "越权读取必须返回空"));

        resolver.withScope(MemoryScope.of("tenant-b", "user-2"),
            () -> assertTrue(store.find(foreign.id()).isPresent(), "本人应能读到自己的记录"));
    }

    @Test
    @DisplayName("列举结果只含当前作用域")
    void 列举结果只含当前作用域() {
        resolver.withScope(MemoryScope.of("tenant-a", "user-1"), () -> {
            store.remember("甲");
            store.remember("乙");
            delegate.inject("丙", MemoryScope.of("tenant-b", "user-2"));

            List<MemoryRecord> listed = store.list(10);

            assertTrue(listed.stream()
                .allMatch(record -> record.scope().equals(MemoryScope.of("tenant-a", "user-1"))));
            assertEquals(2, listed.size());
        });
    }

    @Test
    @DisplayName("作用域嵌套后自动恢复外层作用域")
    void 作用域嵌套后自动恢复外层作用域() {
        resolver.withScope(MemoryScope.of("tenant-a", "user-1"), () -> {
            resolver.withScope(MemoryScope.of("tenant-b", "user-2"),
                () -> assertEquals("tenant-b", resolver.current().tenantId()));
            assertEquals("tenant-a", resolver.current().tenantId());
        });
    }
}
