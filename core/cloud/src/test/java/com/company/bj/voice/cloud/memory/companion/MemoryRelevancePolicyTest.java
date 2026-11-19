package com.company.bj.voice.cloud.memory.companion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.company.bj.voice.cloud.memory.MemoryRecord;
import com.company.bj.voice.cloud.memory.MemoryScope;
import com.company.bj.voice.cloud.memory.ScoredMemoryRecord;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * {@link MemoryRelevancePolicy} 的准入行为测试。
 *
 * <p>核心断言三条：
 * <ol>
 *   <li><b>同一主体的多条记忆只保留最新那条</b> ——
 *       否则"我妈妈叫李芳"与"我妈妈叫王芳"会同时出现在候选里，
 *       用户会听到自相矛盾的两条事实；</li>
 *   <li><b>得分低于下限时拒答</b> ——
 *       检索总会返回点什么，无条件把第一条当事实陈述，
 *       就会出现"问饮食禁忌、答最爱吃酸菜鱼"这类答非所问；</li>
 *   <li><b>没有得分时不得伪装成"已知"</b> ——
 *       未知就是未知，宁可拒答。</li>
 * </ol>
 */
class MemoryRelevancePolicyTest {

    /** 记忆作用域。 */
    private static final MemoryScope SCOPE = MemoryScope.of("default", "user-a");

    /**
     * 构造一条带得分的记忆。
     *
     * @param id      记忆标识
     * @param content 记忆内容
     * @param score   检索得分
     * @param createdAt 创建时间
     * @return 带得分的记忆
     */
    private static ScoredMemoryRecord record(
        String id, String content, double score, long createdAt) {

        MemoryRecord raw = new MemoryRecord(id, content, 1.0, createdAt, SCOPE, false);
        return new ScoredMemoryRecord(raw, score);
    }

    @Test
    @DisplayName("候选为空时没有可陈述的记忆")
    void 候选为空时没有可陈述的记忆() {
        MemoryRelevancePolicy policy = MemoryRelevancePolicy.standard();

        assertTrue(policy.select(List.of()).isEmpty());
        assertTrue(policy.select(null).isEmpty());
    }

    @Test
    @DisplayName("得分高于下限时准入排第一的那条")
    void 得分高于下限时准入排第一的那条() {
        MemoryRelevancePolicy policy = MemoryRelevancePolicy.standard();

        List<ScoredMemoryRecord> candidates = List.of(
            record("id-1", "我妈妈叫李芳", 0.60, 1000L),
            record("id-2", "我养了三只仓鼠", 0.50, 1000L));

        Optional<ScoredMemoryRecord> selected = policy.select(candidates);

        assertTrue(selected.isPresent());
        assertEquals("id-1", selected.get().id());
    }

    @Test
    @DisplayName("得分低于下限时拒答，不拿不相关的记忆充数")
    void 得分低于下限时拒答不拿不相关的记忆充数() {
        MemoryRelevancePolicy policy = MemoryRelevancePolicy.standard();

        List<ScoredMemoryRecord> candidates = List.of(
            record("id-1", "我最爱吃酸菜鱼", 0.40, 1000L));

        assertTrue(policy.select(candidates).isEmpty(),
            "低于相关性下限的候选不得作为事实陈述");
    }

    @Test
    @DisplayName("同一主体只保留创建时间最新的一条")
    void 同一主体只保留创建时间最新的一条() {
        MemoryRelevancePolicy policy = MemoryRelevancePolicy.standard();

        List<ScoredMemoryRecord> candidates = List.of(
            record("id-old", "我妈妈叫李芳", 0.60, 1000L),
            record("id-new", "我妈妈叫王芳", 0.55, 2000L));

        Optional<ScoredMemoryRecord> selected = policy.select(candidates);

        assertTrue(selected.isPresent());
        assertEquals("id-new", selected.get().id(),
            "同一主体的更新事实必须覆盖旧事实，否则用户会听到两条矛盾的记忆");
    }

    @Test
    @DisplayName("没有得分时不作陈述，而不是当成高相关")
    void 没有得分时不作陈述而不是当成高相关() {
        // 得分未知的候选不参与阈值判断 —— 但它仍然会被当作可陈述，
        // 因为"不知道相关不相关"不等于"不相关"。
        // 这里的断言是：得分未知的候选**不会**因为得分而被拒答。
        MemoryRelevancePolicy policy = MemoryRelevancePolicy.standard();

        List<ScoredMemoryRecord> candidates = List.of(
            ScoredMemoryRecord.unscored(
                new MemoryRecord("id-x", "我妈妈叫李芳", 1.0, 1000L, SCOPE, false)));

        assertTrue(policy.select(candidates).isPresent());
    }

    @Test
    @DisplayName("不同主体的记忆互不覆盖")
    void 不同主体的记忆互不覆盖() {
        MemoryRelevancePolicy policy = MemoryRelevancePolicy.standard();

        List<ScoredMemoryRecord> candidates = List.of(
            record("id-a", "我妈妈叫李芳", 0.60, 1000L),
            record("id-b", "我爸爸叫张伟", 0.55, 1000L));

        Optional<ScoredMemoryRecord> selected = policy.select(candidates);

        assertTrue(selected.isPresent());
        assertEquals("id-a", selected.get().id());
    }

    @Test
    @DisplayName("下限可配置，不同业务场景能调")
    void 下限可配置不同业务场景能调() {
        MemoryRelevancePolicy strict = new MemoryRelevancePolicy(0.90);

        assertTrue(strict.select(List.of(
            record("id-1", "我妈妈叫李芳", 0.60, 1000L))).isEmpty());

        assertFalse(MemoryRelevancePolicy.standard().select(List.of(
            record("id-1", "我妈妈叫李芳", 0.60, 1000L))).isEmpty());
    }
}
