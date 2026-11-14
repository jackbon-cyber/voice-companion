package com.company.bj.voice.cloud.memory;

import com.company.bj.voice.cloud.config.MemoryProperties;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.List;
import java.util.Map;
import java.util.NoSuchElementException;
import java.util.Optional;
import java.util.UUID;

/**
 * 工作记忆存储。
 *
 * <p>工作记忆保存「正在做的事」——一组带状态的任务项，
 * 状态在 {@code TODO → IN_PROGRESS → DONE} 之间流转。
 *
 * <p><b>作用域隔离</b>：任务项按作用域分组存放，跨作用域的任务项互相不可见。
 * 与长期记忆用 Chroma 的服务端 {@code where} 过滤实现隔离不同，
 * 工作记忆是进程内数据，用<b>按作用域分桶</b>的方式隔离更直接。
 *
 * <p><b>持久化</b>：每次变更后把当前作用域的任务项写入 JSON 文件。
 * 进程重启后，新实例在<b>首次访问某个作用域</b>时从对应文件恢复 ——
 * 恢复是<b>按作用域懒加载</b>的：构造期还不知道调用方会用哪个作用域，
 * 而构造期就把所有作用域的文件都读一遍既浪费又会读到不属于本次会话的数据。
 *
 * <p><b>分桶与持久化的通用实现</b>由 {@link ScopedJsonStore} 承担，
 * 作用域键格式由 {@link ScopeKeys} 单独拥有 —— 工作记忆与情景记忆共用同一套隔离语义，
 * 不各自复制一份。
 */
public class WorkingMemoryStore {

    /** 持久化文件的目录名，位于 {@code data-path} 之下。 */
    private static final String PERSIST_DIRECTORY = "working-memory";

    /** 未配置文件名时使用的默认文件名。 */
    private static final String DEFAULT_FILE_NAME = "working-memory.json";

    /** 任务项列表的反序列化模板。 */
    private static final TypeReference<List<TaskItem>> TASK_LIST_TYPE = new TypeReference<>() {
    };

    private final ScopeResolver resolver;
    private final ScopedJsonStore<TaskItem> store;

    /**
     * 构造不带持久化的工作记忆存储。
     *
     * @param resolver 作用域解析器
     */
    public WorkingMemoryStore(ScopeResolver resolver) {
        this(resolver, null, new ObjectMapper());
    }

    /**
     * 构造带持久化的工作记忆存储。
     *
     * @param resolver   作用域解析器
     * @param properties 记忆配置，提供持久化路径；为 {@code null} 时不做持久化
     */
    public WorkingMemoryStore(ScopeResolver resolver, MemoryProperties properties) {
        this(resolver, properties, new ObjectMapper());
    }

    /**
     * 构造带持久化的工作记忆存储。
     *
     * @param resolver   作用域解析器
     * @param properties 记忆配置，提供持久化路径；为 {@code null} 时不做持久化
     * @param mapper     JSON 序列化器
     */
    public WorkingMemoryStore(ScopeResolver resolver, MemoryProperties properties, ObjectMapper mapper) {
        this.resolver = resolver;
        this.store = new ScopedJsonStore<>(PERSIST_DIRECTORY, DEFAULT_FILE_NAME, TASK_LIST_TYPE,
            TaskItem::id, properties == null ? null : new WorkingMemoryProperties(properties), mapper);
    }

    /**
     * 新增一个任务项，初始状态为 {@link TaskItem.Status#TODO}。
     *
     * @param description 任务描述
     * @return 新建的任务项
     * @throws IllegalStateException 当前没有活动作用域时抛出
     */
    public TaskItem addTask(String description) {
        MemoryScope scope = resolver.current();
        TaskItem task = new TaskItem(UUID.randomUUID().toString(), description,
            TaskItem.Status.TODO, System.currentTimeMillis());
        bucket(scope).put(task.id(), task);
        persist(scope);
        return task;
    }

    /**
     * 更新任务项的状态。
     *
     * @param id     任务标识
     * @param status 目标状态
     * @return 更新后的任务项
     * @throws IllegalStateException   当前没有活动作用域时抛出
     * @throws NoSuchElementException 任务不存在时抛出
     */
    public TaskItem updateStatus(String id, TaskItem.Status status) {
        MemoryScope scope = resolver.current();
        Map<String, TaskItem> bucket = bucket(scope);
        TaskItem existing = bucket.get(id);
        if (existing == null) {
            throw new NoSuchElementException("task not found: " + id);
        }
        TaskItem updated = new TaskItem(existing.id(), existing.description(),
            status, existing.createdAt());
        bucket.put(id, updated);
        persist(scope);
        return updated;
    }

    /**
     * 按标识读取任务项。
     *
     * @param id 任务标识
     * @return 任务项，不存在时为空
     * @throws IllegalStateException 当前没有活动作用域时抛出
     */
    public Optional<TaskItem> task(String id) {
        MemoryScope scope = resolver.current();
        return Optional.ofNullable(bucket(scope).get(id));
    }

    /**
     * 列出当前作用域下的全部任务项。
     *
     * @return 任务项列表
     * @throws IllegalStateException 当前没有活动作用域时抛出
     */
    public List<TaskItem> tasks() {
        MemoryScope scope = resolver.current();
        return List.copyOf(bucket(scope).values());
    }

    /**
     * 取出当前作用域的任务桶。
     *
     * @param scope 作用域
     * @return 任务桶
     */
    private Map<String, TaskItem> bucket(MemoryScope scope) {
        return store.bucket(scope);
    }

    /**
     * 把当前作用域的任务项写入持久化文件。
     *
     * @param scope 作用域
     * @throws MemoryPersistenceException 写盘失败时抛出
     */
    private void persist(MemoryScope scope) {
        store.persist(scope, bucket(scope).values(), "working memory");
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
    private record WorkingMemoryProperties(MemoryProperties properties)
        implements ScopedJsonStore.MemoryPropertiesHolder {

        @Override
        public String dataPath() {
            return properties.getDataPath();
        }

        @Override
        public String fileName() {
            return properties.getWorkingMemoryFile();
        }
    }
}
