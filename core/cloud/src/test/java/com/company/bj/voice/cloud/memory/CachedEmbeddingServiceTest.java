package com.company.bj.voice.cloud.memory;

import static org.assertj.core.api.Assertions.assertThat;

import com.company.bj.voice.cloud.embed.EmbeddingService;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.Test;

/**
 * 查询向量缓存的行为验证。
 *
 * <p>缓存的价值在于<b>省掉一次真实的模型调用</b>，因此断言落在
 * 「底层服务被调用了几次」上，而不是向量内容本身。
 */
class CachedEmbeddingServiceTest {

    /** 默认缓存存活秒数，与 {@code MemoryProperties.getQueryCacheTtlSeconds()} 一致。 */
    private static final long TTL_SECONDS = 60L;

    @Test
    void 相同文本在有效期内只调用一次底层服务() {
        CountingEmbeddingService delegate = new CountingEmbeddingService();
        CachedEmbeddingService cached = new CachedEmbeddingService(delegate, TTL_SECONDS);

        double[] first = cached.embed("查询文本");
        double[] second = cached.embed("查询文本");

        assertThat(delegate.callCount()).isEqualTo(1);
        assertThat(second).containsExactly(first);
    }

    @Test
    void 不同文本分别缓存() {
        CountingEmbeddingService delegate = new CountingEmbeddingService();
        CachedEmbeddingService cached = new CachedEmbeddingService(delegate, TTL_SECONDS);

        cached.embed("文本一");
        cached.embed("文本二");

        assertThat(delegate.callCount()).isEqualTo(2);
    }

    @Test
    void 过期后重新调用底层服务() {
        CountingEmbeddingService delegate = new CountingEmbeddingService();
        // TTL 为 0 秒意味着写入即过期，用于验证过期路径。
        CachedEmbeddingService cached = new CachedEmbeddingService(delegate, 0L);

        cached.embed("查询文本");
        cached.embed("查询文本");

        assertThat(delegate.callCount()).isEqualTo(2);
    }

    @Test
    void 批量路径不走缓存直接调用底层服务() {
        CountingEmbeddingService delegate = new CountingEmbeddingService();
        CachedEmbeddingService cached = new CachedEmbeddingService(delegate, TTL_SECONDS);

        List<double[]> vectors = cached.embed(List.of("文本一", "文本二"));

        assertThat(vectors).hasSize(2);
        assertThat(delegate.callCount()).isEqualTo(1);
    }

    @Test
    void 调用方改写返回的向量不会污染缓存() {
        CountingEmbeddingService delegate = new CountingEmbeddingService();
        CachedEmbeddingService cached = new CachedEmbeddingService(delegate, TTL_SECONDS);

        double[] first = cached.embed("查询文本");
        double[] original = Arrays.copyOf(first, first.length);

        // 调用方拿到向量后做归一化/缩放这类写操作 —— 缓存不能因此被污染，
        // 否则后续每一次命中都会拿到被改写的向量，模型输入随之静默出错。
        first[0] = 999.0;

        double[] second = cached.embed("查询文本");

        assertThat(second).containsExactly(original);
        // 底层服务只应被调用一次：说明第二次命中的是缓存而非重新计算。
        assertThat(delegate.callCount()).isEqualTo(1);
    }

    @Test
    void 底层服务的向量被改写也不会污染缓存() {
        CountingEmbeddingService delegate = new CountingEmbeddingService();
        CachedEmbeddingService cached = new CachedEmbeddingService(delegate, TTL_SECONDS);

        double[] first = cached.embed("查询文本");
        double[] original = Arrays.copyOf(first, first.length);

        // 委托方仍持有自己那份数组，若缓存存的是引用而非副本，
        // 委托方事后改写就会污染缓存。
        first[0] = 888.0;

        double[] second = cached.embed("查询文本");

        assertThat(second).containsExactly(original);
    }

    /**
     * 记录调用次数的桩嵌入服务。
     */
    private static final class CountingEmbeddingService implements EmbeddingService {

        /** 批量调用的次数。 */
        private final AtomicInteger batchCalls = new AtomicInteger();

        @Override
        public List<double[]> embed(List<String> texts) {
            batchCalls.incrementAndGet();
            List<double[]> vectors = new java.util.ArrayList<>(texts.size());
            for (int i = 0; i < texts.size(); i++) {
                vectors.add(new double[] {texts.get(i).length(), 1.0});
            }
            return vectors;
        }

        /**
         * 返回底层服务被调用的次数。
         *
         * @return 调用次数
         */
        int callCount() {
            return batchCalls.get();
        }
    }
}

