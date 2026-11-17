package com.company.bj.voice.cloud.memory.companion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.company.bj.voice.cloud.memory.LongTermStore;
import com.company.bj.voice.cloud.memory.MemoryRecord;
import com.company.bj.voice.cloud.memory.MemoryScope;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * {@link MemoryUpdateService} 的行为测试。
 *
 * <p>用内存假存储验证三条核心性质：
 * 幂等（同一内容不重复写）、覆盖（改口后旧记录归档）、可追溯（归档记录仍可查）。
 */
class MemoryUpdateServiceTest {

    /** 内存假存储：记录被归档的条目，以验证"归档而非物理删除"。 */
    private static final class InMemoryStore implements LongTermStore {
        private final List<MemoryRecord> records = new ArrayList<>();
        private int counter;

        @Override
        public MemoryRecord remember(String content) {
            return remember(content, 1.0);
        }

        @Override
        public MemoryRecord remember(String content, double weight) {
            counter++;
            MemoryRecord record = new MemoryRecord(
                "id-" + counter, content, weight, System.currentTimeMillis(),
                MemoryScope.of("default", "default"), false);
            records.add(record);
            return record;
        }

        @Override
        public Optional<MemoryRecord> find(String id) {
            return records.stream().filter(record -> record.id().equals(id)).findFirst();
        }

        @Override
        public List<MemoryRecord> search(String query, int topK) {
            List<MemoryRecord> hits = new ArrayList<>();
            for (MemoryRecord record : records) {
                if (!record.archived() && record.content().contains(query.substring(0, 1))) {
                    hits.add(record);
                }
            }
            return hits.size() > topK ? hits.subList(0, topK) : hits;
        }

        @Override
        public List<MemoryRecord> list(int topK) {
            return records.stream().filter(record -> !record.archived()).toList();
        }

        @Override
        public boolean forget(String id) {
            for (int index = 0; index < records.size(); index++) {
                MemoryRecord record = records.get(index);
                if (record.id().equals(id)) {
                    records.set(index, new MemoryRecord(
                        record.id(), record.content(), record.weight(), record.createdAt(),
                        record.scope(), true));
                    return true;
                }
            }
            return false;
        }

        @Override
        public List<MemoryRecord> archived(int topK) {
            return records.stream().filter(MemoryRecord::archived).toList();
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

    /** 被测服务。 */
    private final InMemoryStore store = new InMemoryStore();

    /** 记忆更新服务。 */
    private final MemoryUpdateService service =
        new MemoryUpdateService(store, FingerprintCalculator.lexical());

    @Test
    @DisplayName("首次写入创建新记录")
    void 首次写入创建新记录() {
        MemoryUpdateService.UpdateOutcome outcome = service.upsert("我妈妈叫李芳");

        assertEquals(MemoryUpdateService.UpdateOutcome.UpdateStatus.CREATED, outcome.status());
        assertNotNull(outcome.record());
        assertFalse(outcome.archivedPrevious());
    }

    @Test
    @DisplayName("同一内容重复写入不产生第二条记录")
    void 同一内容重复写入不产生第二条记录() {
        service.upsert("我妈妈叫李芳");
        MemoryUpdateService.UpdateOutcome second = service.upsert("我妈妈叫李芳");

        assertEquals(MemoryUpdateService.UpdateOutcome.UpdateStatus.UNCHANGED, second.status());
        assertEquals(1, store.list(10).size());
    }

    @Test
    @DisplayName("语义等价的表述不产生第二条记录")
    void 语义等价的表述不产生第二条记录() {
        service.upsert("我妈妈叫李芳");
        MemoryUpdateService.UpdateOutcome second = service.upsert("我妈妈叫李芳。");

        assertEquals(MemoryUpdateService.UpdateOutcome.UpdateStatus.UNCHANGED, second.status());
        assertEquals(1, store.list(10).size());
    }

    @Test
    @DisplayName("改口后旧记录被归档而非物理删除")
    void 改口后旧记录被归档而非物理删除() {
        service.upsert("我妈妈叫李芳");
        MemoryUpdateService.UpdateOutcome outcome = service.upsert("我妈妈叫王芳");

        assertEquals(MemoryUpdateService.UpdateOutcome.UpdateStatus.UPDATED, outcome.status());
        assertTrue(outcome.archivedPrevious());
        assertNotNull(outcome.superseded());
    }

    @Test
    @DisplayName("旧事实归档后仍可追溯")
    void 旧事实归档后仍可追溯() {
        service.upsert("我妈妈叫李芳");
        service.upsert("我妈妈叫王芳");

        List<MemoryRecord> archived = store.archived(10);
        assertEquals(1, archived.size());
        assertEquals("我妈妈叫李芳", archived.get(0).content());
        assertTrue(store.find(archived.get(0).id()).isPresent(),
            "归档记录必须仍在存储中可查");
    }

    @Test
    @DisplayName("不同主体的同类内容不互相取代")
    void 不同主体的同类内容不互相取代() {
        service.upsert("我妈妈叫李芳");
        MemoryUpdateService.UpdateOutcome outcome = service.upsert("我姐姐叫李芳");

        assertEquals(MemoryUpdateService.UpdateOutcome.UpdateStatus.CREATED, outcome.status());
        assertFalse(outcome.archivedPrevious());
    }

    @Test
    @DisplayName("空白内容被拒绝且不写入")
    void 空白内容被拒绝且不写入() {
        MemoryUpdateService.UpdateOutcome outcome = service.upsert("   ");

        assertEquals(MemoryUpdateService.UpdateOutcome.UpdateStatus.REJECTED, outcome.status());
        assertNull(outcome.record());
        assertEquals(0, store.list(10).size());
    }
}
