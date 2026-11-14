package com.company.bj.voice.cloud.memory;

import com.company.bj.voice.cloud.embed.EmbeddingService;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ConcurrentMap;

/**
 * 带 TTL 的查询向量缓存。
 *
 * <p>把「同一段查询文本 → 同一个向量」这件事缓存住，省掉一次真实的模型调用。
 * 这条路径是<b>高频</b>的：每一次记忆检索、每一次知识库检索都要算一次查询向量，
 * 而用户的追问往往与上一问只差几个字，逐字重算纯属浪费。
 *
 * <p><b>为什么批量路径不走缓存</b>：批量嵌入用于<b>摄取</b>，
 * 而摄取是首次写入 —— 文本此前没有被嵌入过，缓存里必然没有命中项，
 * 走缓存只是白白多一次哈希查找。批量路径直接调 delegate。
 *
 * <p><b>装配位置</b>：本类必须包在真实嵌入服务的<b>外面</b>，
 * 且知识库检索器与长期记忆存储都应使用<b>缓存后的实例</b>，
 * 否则缓存形同虚设。
 */
public class CachedEmbeddingService implements EmbeddingService {

    /** 缓存条目默认容量。 */
    private static final int DEFAULT_CAPACITY = 256;

    /** 缓存存活秒数的默认值。 */
    private static final long DEFAULT_TTL_SECONDS = 60L;

    /** 每秒毫秒数。 */
    private static final long MILLIS_PER_SECOND = 1000L;

    /** 被缓存的向量。 */
    private final ConcurrentMap<String, CacheEntry> entries = new ConcurrentHashMap<>(DEFAULT_CAPACITY);

    private final EmbeddingService delegate;
    private final long ttlMillis;

    /**
     * 构造缓存包装器。
     *
     * @param delegate   被包装的真实嵌入服务
     * @param ttlSeconds 缓存存活秒数，非正数表示条目写入即过期
     */
    public CachedEmbeddingService(EmbeddingService delegate, long ttlSeconds) {
        this.delegate = delegate;
        this.ttlMillis = ttlSeconds * MILLIS_PER_SECOND;
    }

    /**
     * 构造缓存包装器，使用默认 TTL（{@value #DEFAULT_TTL_SECONDS} 秒）。
     *
     * @param delegate 被包装的真实嵌入服务
     */
    public CachedEmbeddingService(EmbeddingService delegate) {
        this(delegate, DEFAULT_TTL_SECONDS);
    }

    @Override
    public double[] embed(String text) {
        long now = System.currentTimeMillis();
        CacheEntry cached = entries.get(text);
        if (cached != null && !cached.isExpired(now)) {
            // 交出副本：缓存里的数组一旦被调用方改写，
            // 后续每一次命中都会拿到被污染的向量，且污染会静默扩散到模型输入。
            return Arrays.copyOf(cached.vector(), cached.vector().length);
        }
        double[] vector = delegate.embed(text);
        // 存入副本：委托方仍持有它自己那份数组，
        // 若直接存引用，对方事后改写就会污染缓存。
        double[] stored = Arrays.copyOf(vector, vector.length);
        entries.put(text, new CacheEntry(stored, now + ttlMillis));
        return Arrays.copyOf(stored, stored.length);
    }

    @Override
    public List<double[]> embed(List<String> texts) {
        // 批量路径对应摄取场景，缓存命中不了，直接调 delegate。
        return delegate.embed(texts);
    }

    /**
     * 清空缓存。
     */
    public void invalidateAll() {
        entries.clear();
    }

    /**
     * 缓存条目。
     *
     * <p><b>关于 record 的不可变性与 {@code double[]} 组件</b>：
     * record 只保证<b>组件引用</b>不可变（组件本身是 {@code final} 的），
     * 并不保证组件<b>指向的对象</b>不可变。{@code double[]} 是可变对象，
     * 因此本条目的「不可变」承诺只覆盖「数组引用不可被替换」，
     * 不覆盖「数组内容不可被改写」—— 这正是 {@link CachedEmbeddingService}
     * 在读写两侧都做防御性拷贝的原因。
     *
     * <p><b>另一个后果</b>：record 的 {@code equals} / {@code hashCode} 对数组组件
     * 采用<b>引用语义</b>（{@code Object.equals} 的数组身份比较），而非逐元素比较。
     * 因此 {@code CacheEntry} <b>不适合</b>作为 map 的 key ——
     * 两个内容完全相同但数组引用不同的条目会被判为不相等。
     * 另一种表示方式是把向量存成 {@code List<Double>}：它逐元素比较，可以安全作 key，
     * 代价是每次命中都要做一次「数组 → List」的装箱转换，热路径上开销明显。
     * 本类的条目只按<b>文本</b>做 key（{@code entries} 的 key 是文本本身），
     * {@code CacheEntry} 仅作 value，故保留 {@code double[]} + 防御性拷贝的组合：
     * 命中路径零额外分配，且缓存内容不会被外部改写。
     *
     * @param vector    向量
     * @param expiresAt 过期时间戳（epoch 毫秒）
     */
    private record CacheEntry(double[] vector, long expiresAt) {

        /**
         * 判断条目是否已过期。
         *
         * @param now 当前时间戳（epoch 毫秒）
         * @return 是否已过期
         */
        boolean isExpired(long now) {
            return now >= expiresAt;
        }
    }
}
