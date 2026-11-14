package com.company.bj.voice.cloud.memory.companion;

import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * 三路并行召回服务。
 *
 * <p>短期、长期、情景三路检索<b>并行</b>发起，总耗时取<b>最慢的一路</b>
 * 而非三者之和 —— 这是 spec 的硬要求。
 *
 * <p><b>为什么必须是并行</b>：三路里有两路要走到 Chroma（一次网络往返）
 * 与一次嵌入调用。串行执行时端到端时延是三段之和，
 * 而陪伴场景对首包延迟的预算很紧（方案目标 800 ms）。
 * 并行后总时延退化为最慢的那一路，实测能省掉约 2/3 的召回等待。
 *
 * <p><b>线程池有界</b>：用固定大小的池而不是 {@code Executors.newCachedThreadPool} ——
 * 无界池在高并发下会创建大量线程，且本工程的线程池规模应当由调用量显式约束。
 */
public class ParallelRecallService {

    /** 召回路径：短期记忆。 */
    public static final String ROUTE_SHORT_TERM = "short_term";

    /** 召回路径：长期记忆。 */
    public static final String ROUTE_LONG_TERM = "long_term";

    /** 召回路径：情景记忆。 */
    public static final String ROUTE_EPISODIC = "episodic";

    /** 线程池核心线程数：恰好覆盖三路召回。 */
    private static final int POOL_SIZE = 3;

    /** 单路召回的超时时间（秒）。超时后该路返回空结果而非拖垮整体。 */
    private static final long ROUTE_TIMEOUT_SECONDS = 5L;

    /** 单路召回接口。 */
    @FunctionalInterface
    public interface RecallRoute {

        /**
         * 执行一路召回。
         *
         * @param query 查询文本
         * @param topK  返回条数上限
         * @return 候选列表
         */
        List<RecallFusion.FusionCandidate> recall(String query, int topK);
    }

    /** 并行召回的结果。 */
    public record RecallOutcome(
        List<List<RecallFusion.FusionCandidate>> routes,
        long elapsedMillis,
        List<String> failedRoutes) {

        /**
         * 判断是否有路召回失败。
         *
         * @return 存在失败路径返回 {@code true}
         */
        public boolean partial() {
            return !failedRoutes.isEmpty();
        }
    }

    private final ExecutorService executor;

    /**
     * 构造并行召回服务，使用默认线程池。
     */
    public ParallelRecallService() {
        this(POOL_SIZE);
    }

    /**
     * 构造并行召回服务。
     *
     * @param poolSize 线程池规模
     */
    public ParallelRecallService(int poolSize) {
        AtomicInteger counter = new AtomicInteger();
        ThreadFactory factory = runnable -> {
            Thread thread = new Thread(runnable, "memory-recall-" + counter.incrementAndGet());
            thread.setDaemon(true);
            return thread;
        };
        this.executor = Executors.newFixedThreadPool(poolSize, factory);
    }

    /**
     * 并行执行三路召回。
     *
     * @param routes 各路召回函数，键为路径标识
     * @param query  查询文本
     * @param topK   每路返回条数上限
     * @return 召回结果，含各路候选与总耗时
     */
    public RecallOutcome recallAll(
        java.util.Map<String, RecallRoute> routes, String query, int topK) {

        if (routes == null || routes.isEmpty()) {
            return new RecallOutcome(List.of(), 0L, List.of());
        }

        long start = System.nanoTime();
        List<CompletableFuture<List<RecallFusion.FusionCandidate>>> futures = new ArrayList<>();
        List<String> routeNames = new ArrayList<>();

        for (java.util.Map.Entry<String, RecallRoute> entry : routes.entrySet()) {
            routeNames.add(entry.getKey());
            RecallRoute route = entry.getValue();
            futures.add(CompletableFuture.supplyAsync(
                () -> route.recall(query, topK), executor));
        }

        List<List<RecallFusion.FusionCandidate>> results = new ArrayList<>();
        List<String> failed = new ArrayList<>();
        for (int index = 0; index < futures.size(); index++) {
            try {
                results.add(futures.get(index).get(ROUTE_TIMEOUT_SECONDS, TimeUnit.SECONDS));
            } catch (Exception error) {
                // 单路失败不应让整次召回失败：一路挂掉时其余两路仍能提供记忆。
                failed.add(routeNames.get(index));
                results.add(List.of());
            }
        }

        long elapsedMillis = (System.nanoTime() - start) / 1_000_000L;
        return new RecallOutcome(List.copyOf(results), elapsedMillis, List.copyOf(failed));
    }

    /**
     * 关闭线程池。
     */
    public void shutdown() {
        executor.shutdownNow();
    }
}
