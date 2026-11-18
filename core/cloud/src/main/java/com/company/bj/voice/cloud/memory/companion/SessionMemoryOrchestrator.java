package com.company.bj.voice.cloud.memory.companion;

import com.company.bj.voice.cloud.memory.MemoryRecord;
import com.company.bj.voice.cloud.memory.MemoryScope;
import com.company.bj.voice.cloud.memory.ScopeResolver;
import com.company.bj.voice.cloud.memory.SessionOwnerRegistry;
import java.util.List;

/**
 * 会话记忆编排服务。
 *
 * <p>把「一轮对话」与「记忆」接起来：写入用户说过的事实、按当前作用域召回事实，
 * 并把召回结果作为**引用来源**交给上层生成回复。
 *
 * <p><b>为什么这一层必须存在</b>：记忆的写入与召回此前只存在于类里，
 * 没有接到运行链路上 —— 云端能收到上行意图，但从不写记忆、也从不召回。
 * 表现为"机器人每次都是第一次见面"，而代码里看不出缺了什么。
 *
 * <p><b>作用域绑定在这一层完成</b>：{@link ScopeResolver} 是 {@code ThreadLocal} 实现，
 * 跨线程不可见。上行消息的处理线程与调用方未必是同一个线程，
 * 因此本类在每个操作前显式用 {@code withScope} 绑定作用域，
 * 保证「读到的记忆一定属于本会话的用户」。
 *
 * <p><b>隔离不依赖调用方</b>：本类不接受作用域入参 ——
 * 作用域永远由会话标识推导，调用方没有机会传错。
 */
public class SessionMemoryOrchestrator {

    /** 召回条数上限。 */
    public static final int RECALL_LIMIT = 5;

    /** 陪伴域长期记忆存储。带作用域强制过滤。 */
    private final ScopedCompanionMemoryStore store;

    /** 作用域解析器。 */
    private final ScopeResolver scopeResolver;

    /** 会话归属注册表。 */
    private final SessionOwnerRegistry ownerRegistry;

    /** 记忆分类器。 */
    private final CompanionMemoryClassifier classifier;

    /** 记忆更新服务。 */
    private final MemoryUpdateService updateService;

    /**
     * 构造编排服务。
     *
     * @param store          陪伴域长期记忆存储（带作用域强制过滤）
     * @param scopeResolver  作用域解析器
     * @param ownerRegistry  会话归属注册表
     * @param classifier     记忆分类器
     * @param updateService  记忆更新服务
     * @throws IllegalArgumentException 参数为 null 时抛出
     */
    public SessionMemoryOrchestrator(
        ScopedCompanionMemoryStore store,
        ScopeResolver scopeResolver,
        SessionOwnerRegistry ownerRegistry,
        CompanionMemoryClassifier classifier,
        MemoryUpdateService updateService) {

        if (store == null || scopeResolver == null || ownerRegistry == null
            || classifier == null || updateService == null) {
            throw new IllegalArgumentException("编排服务依赖不能为 null");
        }
        this.store = store;
        this.scopeResolver = scopeResolver;
        this.ownerRegistry = ownerRegistry;
        this.classifier = classifier;
        this.updateService = updateService;
    }

    /**
     * 记录一轮对话里用户说过的话。
     *
     * <p>只有<b>长期类</b>的记忆才写入：一次性指令与寒暄写进去是噪音，
     * 当次情绪属于情景记忆，不进长期层。
     *
     * @param sessionId 会话标识
     * @param text      用户原话
     * @return 写入结果；未写入时返回 {@link MemoryUpdateService.UpdateOutcome#rejected(String)}
     */
    public MemoryUpdateService.UpdateOutcome remember(String sessionId, String text) {
        if (text == null || text.isBlank()) {
            return MemoryUpdateService.UpdateOutcome.rejected("用户原话为空");
        }
        if (!classifier.shouldPersistLongTerm(text)) {
            return MemoryUpdateService.UpdateOutcome.rejected(
                "不属于长期记忆：" + classifier.classify(text));
        }
        MemoryScope scope = scopeResolverFor(sessionId);
        return scopeResolver.withScopeResult(scope, () -> updateService.upsert(text));
    }

    /**
     * 按当前会话的用户召回记忆。
     *
     * @param sessionId 会话标识
     * @param query     查询文本
     * @param limit     返回条数上限
     * @return 命中的记忆记录；没有命中时返回空列表
     */
    public List<MemoryRecord> recall(String sessionId, String query, int limit) {
        if (query == null || query.isBlank()) {
            return List.of();
        }
        MemoryScope scope = scopeResolverFor(sessionId);
        return scopeResolver.withScopeResult(
            scope, () -> store.search(query, Math.max(1, limit)));
    }

    /**
     * 召回并转成引用来源标识。
     *
     * <p>引用来源是 {@code text-reply} 协议里的 {@code citations} 字段 ——
     * 它让「这条回复依据了哪条记忆」成为**可机器断言**的事实，
     * 而不是只能靠人读回复文本去猜。
     *
     * @param sessionId 会话标识
     * @param query     查询文本
     * @param limit     返回条数上限
     * @return 引用来源标识列表
     */
    public List<String> recallCitations(String sessionId, String query, int limit) {
        return recall(sessionId, query, limit).stream()
                .map(MemoryRecord::id)
                .toList();
    }

    /**
     * 列出当前会话用户的记忆。
     *
     * @param sessionId 会话标识
     * @param limit     返回条数上限
     * @return 记忆记录列表
     */
    public List<MemoryRecord> listForSession(String sessionId, int limit) {
        MemoryScope scope = scopeResolverFor(sessionId);
        return scopeResolver.withScopeResult(
            scope, () -> store.list(Math.max(1, limit)));
    }

    /**
     * 解析会话对应的作用域。
     *
     * @param sessionId 会话标识
     * @return 记忆作用域
     */
    private MemoryScope scopeResolverFor(String sessionId) {
        return ownerRegistry.scopeOf(sessionId);
    }
}
