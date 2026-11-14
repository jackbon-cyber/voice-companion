package com.company.bj.voice.cloud.memory.companion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * {@link ParallelRecallService} 的行为测试。
 *
 * <p>核心断言：<b>总耗时取最慢的一路而非三者之和</b>。
 * 这条断言是本类的存在理由，必须有明确的量化证据。
 */
class ParallelRecallServiceTest {

    /** 单路候选构造器。 */
    private static RecallFusion.FusionCandidate candidate(String id) {
        return new RecallFusion.FusionCandidate(
            id, id, 1.0, CompanionMemoryCategory.RELATIONSHIP_FACT, 0L);
    }

    @Test
    @DisplayName("三路召回并行执行，耗时取最慢者而非求和")
    void 三路召回并行执行耗时取最慢者而非求和() throws Exception {
        // 每路各睡 400 ms。若是串行，总耗时约 1200 ms；并行则约 400 ms。
        int routeDelayMillis = 400;
        int routeCount = 3;
        CountDownLatch allArrived = new CountDownLatch(routeCount);

        Map<String, ParallelRecallService.RecallRoute> routes = new LinkedHashMap<>();
        for (String name : List.of("a", "b", "c")) {
            routes.put(name, (query, topK) -> {
                allArrived.countDown();
                try {
                    // 等待三路都进入，这样总耗时必然是"最慢一路"而不是"错峰进入"。
                    allArrived.await(2, TimeUnit.SECONDS);
                    Thread.sleep(routeDelayMillis);
                } catch (InterruptedException interrupted) {
                    Thread.currentThread().interrupt();
                }
                return List.of(candidate(name));
            });
        }

        try (AutoCloseable ignored = () -> { }) {
            ParallelRecallService service = new ParallelRecallService();
            try {
                ParallelRecallService.RecallOutcome outcome = service.recallAll(routes, "查询", 5);

                assertEquals(3, outcome.routes().size());
                assertFalse(outcome.partial(), "三路都不应失败");

                long serialLowerBound = (long) routeDelayMillis * routeCount;
                long parallelUpperBound = (long) routeDelayMillis * 2;
                assertTrue(outcome.elapsedMillis() < parallelUpperBound,
                    "总耗时 " + outcome.elapsedMillis() + " ms 应接近最慢一路（"
                        + routeDelayMillis + " ms）而非三路之和（" + serialLowerBound + " ms）");
            } finally {
                service.shutdown();
            }
        }
    }

    @Test
    @DisplayName("单路失败不影响其余路的结果")
    void 单路失败不影响其余路的结果() {
        Map<String, ParallelRecallService.RecallRoute> routes = new LinkedHashMap<>();
        routes.put("good", (query, topK) -> List.of(candidate("good-1")));
        routes.put("bad", (query, topK) -> {
            throw new IllegalStateException("模拟存储层故障");
        });

        ParallelRecallService service = new ParallelRecallService();
        try {
            ParallelRecallService.RecallOutcome outcome = service.recallAll(routes, "查询", 5);

            assertTrue(outcome.partial(), "存在失败路径时应标记为部分成功");
            assertEquals(List.of("bad"), outcome.failedRoutes());
            assertEquals(2, outcome.routes().size());
        } finally {
            service.shutdown();
        }
    }

    @Test
    @DisplayName("空路径表返回空结果")
    void 空路径表返回空结果() {
        ParallelRecallService service = new ParallelRecallService();
        try {
            ParallelRecallService.RecallOutcome outcome = service.recallAll(Map.of(), "查询", 5);
            assertEquals(0, outcome.routes().size());
            assertEquals(0L, outcome.elapsedMillis());
            assertFalse(outcome.partial());
        } finally {
            service.shutdown();
        }
    }

    @Test
    @DisplayName("三路各自返回候选")
    void 三路各自返回候选() {
        Map<String, ParallelRecallService.RecallRoute> routes = new LinkedHashMap<>();
        routes.put(ParallelRecallService.ROUTE_SHORT_TERM, (query, topK) -> List.of(candidate("st-1")));
        routes.put(ParallelRecallService.ROUTE_LONG_TERM, (query, topK) -> List.of(candidate("lt-1")));
        routes.put(ParallelRecallService.ROUTE_EPISODIC, (query, topK) -> List.of(candidate("ep-1")));

        ParallelRecallService service = new ParallelRecallService();
        try {
            ParallelRecallService.RecallOutcome outcome = service.recallAll(routes, "查询", 5);

            assertEquals(3, outcome.routes().size());
            assertEquals(1, outcome.routes().get(0).size());
            assertEquals("st-1", outcome.routes().get(0).get(0).id());
            assertEquals("lt-1", outcome.routes().get(1).get(0).id());
            assertEquals("ep-1", outcome.routes().get(2).get(0).id());
        } finally {
            service.shutdown();
        }
    }
}
