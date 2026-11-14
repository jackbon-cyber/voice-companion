package com.company.bj.voice.cloud.memory;

import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Function;

/**
 * 按作用域分桶、并可按作用域持久化为 JSON 文件的通用存储骨架。
 *
 * <p>工作记忆与情景记忆的隔离语义<b>完全一致</b>：都是「按作用域分桶 + 按作用域分文件」，
 * 差别仅在于桶里装的记录类型与默认文件名。把这段逻辑抽到这里，
 * 是为了让<b>作用域键格式只有一处实现</b>（见 {@link ScopeKeys}），
 * 同时让「按作用域懒加载恢复」这套时序也只写一遍。
 *
 * <p><b>懒加载恢复</b>：新实例在首次访问某作用域时（{@code computeIfAbsent} 的映射函数内）
 * 从磁盘恢复该作用域的数据。构造期还不知道调用方会用哪个作用域，
 * 构造期把所有作用域的文件都读一遍既浪费又会读到不属于本次会话的数据。
 *
 * @param <T> 桶内记录类型
 */
class ScopedJsonStore<T> {

    /** 记录按作用域分桶存放。 */
    private final Map<String, Map<String, T>> buckets = new ConcurrentHashMap<>();

    /** 持久化目录名，位于 {@code data-path} 之下。 */
    private final String persistDirectory;

    /** 未配置文件名时使用的默认文件名。 */
    private final String defaultFileName;

    /** 记录类型的反序列化模板。 */
    private final TypeReference<List<T>> listType;

    /** 从记录中取出标识，用于写入桶时作为键。 */
    private final Function<T, String> idExtractor;

    private final MemoryPropertiesHolder properties;
    private final ObjectMapper mapper;

    /**
     * 构造存储骨架。
     *
     * @param persistDirectory 持久化目录名
     * @param defaultFileName  未配置文件名时使用的默认文件名
     * @param listType         记录列表的反序列化模板
     * @param idExtractor      记录标识提取器
     * @param properties       持久化配置提供者，为 {@code null} 时不做持久化
     * @param mapper           JSON 序列化器
     */
    ScopedJsonStore(String persistDirectory, String defaultFileName, TypeReference<List<T>> listType,
        Function<T, String> idExtractor, MemoryPropertiesHolder properties, ObjectMapper mapper) {
        this.persistDirectory = persistDirectory;
        this.defaultFileName = defaultFileName;
        this.listType = listType;
        this.idExtractor = idExtractor;
        this.properties = properties;
        this.mapper = mapper;
    }

    /**
     * 取出（或创建）某个作用域对应的桶，并在首次创建时从磁盘恢复。
     *
     * <p>恢复动作放在 {@code computeIfAbsent} 的映射函数里，保证
     * 「建桶」与「读盘」对同一个桶只发生一次 —— 并发访问下不会重复读盘，
     * 也不会出现「已建桶但没恢复」的窗口期。
     *
     * @param scope 作用域
     * @return 记录桶
     */
    Map<String, T> bucket(MemoryScope scope) {
        return buckets.computeIfAbsent(ScopeKeys.scopeKey(scope), key -> {
            Map<String, T> bucket = new ConcurrentHashMap<>();
            restore(scope, bucket);
            return bucket;
        });
    }

    /**
     * 把某个作用域的记录写入持久化文件。
     *
     * <p>写盘失败会抛出 {@link MemoryPersistenceException}：记录已加进内存，
     * 此刻若静默吞掉异常，调用方会以为「已经存好了」，而重启后数据消失 ——
     * 这类静默丢失比一次显式失败难查得多。
     *
     * @param scope    作用域
     * @param records  待写入的记录
     * @param label    异常消息中的存储类型标识
     * @throws MemoryPersistenceException 写盘失败时抛出
     */
    void persist(MemoryScope scope, Iterable<T> records, String label) {
        if (properties == null) {
            return;
        }
        Path file = persistFile(scope);
        try {
            Files.createDirectories(file.getParent());
            Files.writeString(file, mapper.writeValueAsString(records));
        } catch (IOException e) {
            throw new MemoryPersistenceException("failed to persist " + label + " to " + file, e);
        }
    }

    /**
     * 解析出某个作用域的持久化文件路径。
     *
     * <p>文件名为「配置的文件名去掉 {@code .json} 后缀 + 作用域标识 + {@code .json}」，
     * 于是同一层记忆的不同作用域各占一个文件，不会互相覆盖。
     *
     * @param scope 作用域
     * @return 文件路径
     */
    private Path persistFile(MemoryScope scope) {
        Path base = Path.of(properties.dataPath()).resolve(persistDirectory);
        return base.resolve(ScopeKeys.scopeFileName(properties.fileName(), defaultFileName, scope));
    }

    /**
     * 从持久化文件恢复某个作用域的记录。
     *
     * @param scope  作用域
     * @param bucket 恢复目标桶
     * @throws MemoryPersistenceException 读盘或解析失败时抛出
     */
    private void restore(MemoryScope scope, Map<String, T> bucket) {
        if (properties == null) {
            return;
        }
        Path file = persistFile(scope);
        if (!Files.exists(file)) {
            return;
        }
        try {
            List<T> records = mapper.readValue(Files.readString(file), listType);
            for (T record : records) {
                bucket.put(idExtractor.apply(record), record);
            }
        } catch (IOException e) {
            throw new MemoryPersistenceException("failed to restore " + defaultFileName + " from " + file, e);
        }
    }

    /**
     * 持久化配置的最小抽象。
     *
     * <p>抽出接口而不是直接依赖 {@code MemoryProperties}，是为了让本骨架
     * 不与具体配置类耦合 —— 配置类提供的「路径」与「文件名」两件事各自可能缺席，
     * 用接口表达比传两个可空参数更清晰。
     */
    interface MemoryPropertiesHolder {

        /**
         * 返回持久化数据目录。
         *
         * @return 数据目录
         */
        String dataPath();

        /**
         * 返回该层记忆的持久化文件名。
         *
         * @return 文件名
         */
        String fileName();
    }
}
