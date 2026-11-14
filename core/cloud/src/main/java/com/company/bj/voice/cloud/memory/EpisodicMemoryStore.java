package com.company.bj.voice.cloud.memory;

import com.company.bj.voice.cloud.config.MemoryProperties;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

/**
 * 情景记忆存储。
 *
 * <p>情景记忆记录「发生过什么」——带类型、顺序敏感的事件序列。
 * 与工作记忆一样，它按<b>作用域</b>隔离，跨作用域的情景互相不可见。
 *
 * <p><b>持久化</b>：每次新增情景后写入 JSON 文件；进程重启后，
 * 新实例在<b>首次访问某个作用域</b>时从对应文件恢复（懒加载）。
 *
 * <p><b>分桶与持久化的通用实现</b>由 {@link ScopedJsonStore} 承担，
 * 作用域键格式由 {@link ScopeKeys} 单独拥有 —— 与工作记忆共用同一套隔离语义，
 * 不各自复制一份，否则两份隔离关键例程一旦分叉就会以跨作用域泄漏的形式暴露。
 */
public class EpisodicMemoryStore {

    /** 持久化文件的目录名，位于 {@code data-path} 之下。 */
    private static final String PERSIST_DIRECTORY = "episodic-memory";

    /** 未配置文件名时使用的默认文件名。 */
    private static final String DEFAULT_FILE_NAME = "episodic-memory.json";

    /** 情景列表的反序列化模板。 */
    private static final TypeReference<List<Episode>> EPISODE_LIST_TYPE = new TypeReference<>() {
    };

    private final ScopeResolver resolver;
    private final ScopedJsonStore<Episode> store;

    /**
     * 构造不带持久化的情景记忆存储。
     *
     * @param resolver 作用域解析器
     */
    public EpisodicMemoryStore(ScopeResolver resolver) {
        this(resolver, null, new ObjectMapper());
    }

    /**
     * 构造带持久化的情景记忆存储。
     *
     * @param resolver   作用域解析器
     * @param properties 记忆配置，提供持久化路径；为 {@code null} 时不做持久化
     */
    public EpisodicMemoryStore(ScopeResolver resolver, MemoryProperties properties) {
        this(resolver, properties, new ObjectMapper());
    }

    /**
     * 构造带持久化的情景记忆存储。
     *
     * @param resolver   作用域解析器
     * @param properties 记忆配置，提供持久化路径；为 {@code null} 时不做持久化
     * @param mapper     JSON 序列化器
     */
    public EpisodicMemoryStore(ScopeResolver resolver, MemoryProperties properties, ObjectMapper mapper) {
        this.resolver = resolver;
        this.store = new ScopedJsonStore<>(PERSIST_DIRECTORY, DEFAULT_FILE_NAME, EPISODE_LIST_TYPE,
            Episode::id, properties == null ? null : new EpisodicMemoryProperties(properties), mapper);
    }

    /**
     * 记录一段情景。
     *
     * @param type   情景类型
     * @param events 事件序列，顺序敏感
     * @return 新建的情景
     * @throws IllegalStateException 当前没有活动作用域时抛出
     */
    public Episode record(String type, List<String> events) {
        MemoryScope scope = resolver.current();
        Episode episode = new Episode(UUID.randomUUID().toString(), type, events,
            System.currentTimeMillis(), scope);
        bucket(scope).put(episode.id(), episode);
        persist(scope);
        return episode;
    }

    /**
     * 按标识读取情景。
     *
     * @param id 情景标识
     * @return 情景，不存在或不属于当前作用域时为空
     * @throws IllegalStateException 当前没有活动作用域时抛出
     */
    public Optional<Episode> episode(String id) {
        MemoryScope scope = resolver.current();
        return Optional.ofNullable(bucket(scope).get(id));
    }

    /**
     * 列出当前作用域下的全部情景。
     *
     * @return 情景列表
     * @throws IllegalStateException 当前没有活动作用域时抛出
     */
    public List<Episode> episodes() {
        MemoryScope scope = resolver.current();
        return List.copyOf(bucket(scope).values());
    }

    /**
     * 取出当前作用域的情景桶。
     *
     * @param scope 作用域
     * @return 情景桶
     */
    private Map<String, Episode> bucket(MemoryScope scope) {
        return store.bucket(scope);
    }

    /**
     * 把当前作用域的情景写入持久化文件。
     *
     * @param scope 作用域
     * @throws MemoryPersistenceException 写盘失败时抛出
     */
    private void persist(MemoryScope scope) {
        store.persist(scope, bucket(scope).values(), "episodic memory");
    }

    /**
     * 按作用域构造持久化文件名。
     *
     * @param configuredName 配置的文件名
     * @param scope          作用域
     * @return 文件名
     */
    static String scopeFileName(String configuredName, MemoryScope scope) {
        return ScopeKeys.scopeFileName(configuredName, DEFAULT_FILE_NAME, scope);
    }

    /**
     * 把记忆配置适配为 {@link ScopedJsonStore} 所需的最小视图。
     *
     * @param properties 记忆配置
     */
    private record EpisodicMemoryProperties(MemoryProperties properties)
        implements ScopedJsonStore.MemoryPropertiesHolder {

        @Override
        public String dataPath() {
            return properties.getDataPath();
        }

        @Override
        public String fileName() {
            return properties.getEpisodicMemoryFile();
        }
    }
}
