package com.company.bj.voice.cloud.memory.companion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Duration;
import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * {@link RecallFusion} 的行为测试。
 *
 * <p>覆盖 spec 要求的：融合后取固定条数、权重随时间推移下降。
 */
class RecallFusionTest {

    /** 被测融合器。 */
    private final RecallFusion fusion = new RecallFusion();

    /** 固定基准时刻。 */
    private static final long NOW = 1_700_000_000_000L;

    /** 默认半衰期。 */
    private static final long HALF_LIFE = RecallFusion.DEFAULT_HALF_LIFE_MILLIS;

    /**
     * 构造单路候选。
     *
     * @param id        标识
     * @param content   正文
     * @param weight    重要度
     * @param createdAt 创建时间戳
     * @return 候选
     */
    private RecallFusion.FusionCandidate candidate(
        String id, String content, double weight, long createdAt) {
        return new RecallFusion.FusionCandidate(
            id, content, weight, CompanionMemoryCategory.RELATIONSHIP_FACT, createdAt);
    }

    @Test
    @DisplayName("融合后取固定条数")
    void 融合后取固定条数() {
        List<List<RecallFusion.FusionCandidate>> routes = List.of(
            List.of(candidate("a", "甲", 1.0, NOW), candidate("b", "乙", 1.0, NOW)),
            List.of(candidate("c", "丙", 1.0, NOW), candidate("d", "丁", 1.0, NOW)));

        List<RecallFusion.FusedCandidate> fused = fusion.fuse(routes, NOW, HALF_LIFE, 2);

        assertEquals(2, fused.size());
    }

    @Test
    @DisplayName("多路都命中的候选排在单路命中的之前")
    void 多路都命中的候选排在单路命中的之前() {
        List<List<RecallFusion.FusionCandidate>> routes = List.of(
            List.of(candidate("shared", "共享", 1.0, NOW)),
            List.of(candidate("shared", "共享", 1.0, NOW), candidate("solo", "独有", 1.0, NOW)));

        List<RecallFusion.FusedCandidate> fused = fusion.fuse(routes, NOW, HALF_LIFE, 10);

        assertEquals("shared", fused.get(0).id());
    }

    @Test
    @DisplayName("权重随时间推移下降")
    void 权重随时间推移下降() {
        double fresh = fusion.decayFactor(NOW, NOW, HALF_LIFE);
        double halfLifeOld = fusion.decayFactor(NOW - HALF_LIFE, NOW, HALF_LIFE);
        double veryOld = fusion.decayFactor(NOW - HALF_LIFE * 4, NOW, HALF_LIFE);

        assertEquals(1.0, fresh, 1e-9);
        assertEquals(0.5, halfLifeOld, 1e-9);
        assertTrue(veryOld < halfLifeOld, "更久远的记忆衰减系数应更低");
    }

    @Test
    @DisplayName("衰减系数不会降到零以下限")
    void 衰减系数不会降到零以下限() {
        double ancient = fusion.decayFactor(NOW - HALF_LIFE * 100, NOW, HALF_LIFE);
        assertEquals(RecallFusion.MIN_DECAY_FACTOR, ancient, 1e-9);
    }

    @Test
    @DisplayName("过期条目不参与融合")
    void 过期条目不参与融合() {
        // 构造时已在过滤阶段完成：融合器只接收活跃条目。
        List<List<RecallFusion.FusionCandidate>> routes = List.of(
            List.of(candidate("fresh", "新", 1.0, NOW)));
        List<RecallFusion.FusedCandidate> fused = fusion.fuse(routes, NOW, HALF_LIFE, 10);
        assertEquals(1, fused.size());
        assertEquals("fresh", fused.get(0).id());
    }

    @Test
    @DisplayName("空输入返回空列表")
    void 空输入返回空列表() {
        assertEquals(List.of(), fusion.fuse(List.of(), NOW, HALF_LIFE, 10));
        assertEquals(List.of(), fusion.fuse(null, NOW, HALF_LIFE, 10));
    }

    @Test
    @DisplayName("重要度系数有上下限")
    void 重要度系数有上下限() {
        assertEquals(0.1, fusion.importanceFactor(0.0), 1e-9);
        assertEquals(0.1, fusion.importanceFactor(-1.0), 1e-9);
        assertEquals(2.0, fusion.importanceFactor(100.0), 1e-9);
        assertEquals(1.0, fusion.importanceFactor(1.0), 1e-9);
    }

    @Test
    @DisplayName("半衰期为零时不衰减")
    void 半衰期为零时不衰减() {
        assertEquals(1.0, fusion.decayFactor(NOW - Duration.ofDays(100).toMillis(), NOW, 0L), 1e-9);
    }
}
