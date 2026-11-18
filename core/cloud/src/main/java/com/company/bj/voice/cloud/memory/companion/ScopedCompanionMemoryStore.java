package com.company.bj.voice.cloud.memory.companion;

import com.company.bj.voice.cloud.memory.LongTermStore;
import com.company.bj.voice.cloud.memory.MemoryRecord;
import com.company.bj.voice.cloud.memory.MemoryScope;
import com.company.bj.voice.cloud.memory.ScopeResolver;
import java.util.List;
import java.util.Optional;

/**
 * 陪伴域长期记忆存储。
 *
 * <p><b>这是 9.8 的落地形态</b>：跨用户记忆隔离由<b>存储层强制</b>，
 * 调用方不需要（也无法）传作用域。
 *
 * <p><b>隔离的三道防线</b>：
 * <ol>
 *   <li><b>接口层不收作用域入参</b> —— 调用方没有机会传错或漏传；</li>
 *   <li><b>无活动作用域时直接拒绝</b> —— 而不是退化成某个默认作用域。
 *       退化成默认作用域会让"忘了设作用域"的代码<b>静默地读到别人的数据</b>，
 *       这是最难排查的一类泄漏；</li>
 *   <li><b>读出后再做一次归属校验</b> —— 即使底层存储的实现有疏漏，
 *       越权的记录也不会被交给上层。</li>
 * </ol>
 *
 * <p>第三道防线是"纵深防御"：前两道防的是调用方犯错，第三道防的是实现出错。
 * 成本极低，收益是隔离性不依赖单一环节的正确性。
 */
public class ScopedCompanionMemoryStore implements LongTermStore {

    /** 底层长期记忆存储。 */
    private final LongTermStore delegate;

    /** 作用域解析器。 */
    private final ScopeResolver scopeResolver;

    /**
     * 构造陪伴域长期记忆存储。
     *
     * @param delegate       底层长期记忆存储
     * @param scopeResolver  作用域解析器
     */
    public ScopedCompanionMemoryStore(LongTermStore delegate, ScopeResolver scopeResolver) {
        this.delegate = delegate;
        this.scopeResolver = scopeResolver;
    }

    /**
     * 写入一条记忆。
     *
     * @param content 记忆内容
     * @return 写入后的记录
     * @throws IllegalStateException 当前没有活动作用域时抛出
     */
    @Override
    public MemoryRecord remember(String content) {
        requireScope();
        return delegate.remember(content);
    }

    /**
     * 写入一条记忆并指定权重。
     *
     * @param content 记忆内容
     * @param weight  权重
     * @return 写入后的记录
     * @throws IllegalStateException 当前没有活动作用域时抛出
     */
    @Override
    public MemoryRecord remember(String content, double weight) {
        requireScope();
        return delegate.remember(content, weight);
    }

    /**
     * 按语义检索当前作用域下的记忆。
     *
     * @param query 查询文本
     * @param topK  返回条数上限
     * @return 命中的记录列表
     * @throws IllegalStateException 当前没有活动作用域时抛出
     */
    public List<MemoryRecord> search(String query, int topK) {
        requireScope();
        List<MemoryRecord> found = delegate.search(query, topK);
        return filterByScope(found);
    }

    /**
     * 列出当前作用域下的记忆。
     *
     * @param topK 返回条数上限
     * @return 记录列表
     * @throws IllegalStateException 当前没有活动作用域时抛出
     */
    public List<MemoryRecord> list(int topK) {
        requireScope();
        return filterByScope(delegate.list(topK));
    }

    /**
     * 按标识读取一条记忆。
     *
     * @param id 记录标识
     * @return 记录；不可见时为空
     * @throws IllegalStateException 当前没有活动作用域时抛出
     */
    public Optional<MemoryRecord> find(String id) {
        requireScope();
        Optional<MemoryRecord> found = delegate.find(id);
        if (found.isEmpty()) {
            return Optional.empty();
        }
        MemoryScope scope = scopeResolver.current();
        return scope.equals(found.get().scope()) ? found : Optional.empty();
    }

    /**
     * 遗忘一条记忆（软删除）。
     *
     * @param id 记录标识
     * @return 是否遗忘成功
     * @throws IllegalStateException 当前没有活动作用域时抛出
     */
    public boolean forget(String id) {
        requireScope();
        return delegate.forget(id);
    }

    /**
     * 列出当前作用域下的已归档记忆。
     *
     * @param topK 返回条数上限
     * @return 归档记录列表
     * @throws IllegalStateException 当前没有活动作用域时抛出
     */
    public List<MemoryRecord> archived(int topK) {
        requireScope();
        return filterByScope(delegate.archived(topK));
    }

    /**
     * 清除当前作用域下的全部记忆（含已归档记录）。
     *
     * <p><b>隔离由存储层强制</b>：本方法只清除当前作用域的记录，
     * 绝不会影响其他租户/主体的数据。
     *
     * @return 被清除的记录数
     * @throws IllegalStateException 当前没有活动作用域时抛出
     */
    @Override
    public int clearCurrentScope() {
        requireScope();
        return delegate.clearCurrentScope();
    }

    /**
     * 把多条长期记忆归并为一条新记录。
     *
     * @param ids 待归并的记录标识列表
     * @return 归并产生的新记录
     * @throws IllegalStateException 当前没有活动作用域时抛出
     */
    @Override
    public Optional<MemoryRecord> consolidate(List<String> ids) {
        requireScope();
        return delegate.consolidate(ids);
    }

    /**
     * 过滤掉不属于当前作用域的记录。
     *
     * @param records 候选记录
     * @return 属于当前作用域的记录
     */
    private List<MemoryRecord> filterByScope(List<MemoryRecord> records) {
        MemoryScope scope = scopeResolver.current();
        return records.stream()
            .filter(record -> scope.equals(record.scope()))
            .toList();
    }

    /**
     * 要求当前线程存在活动作用域。
     *
     * @throws IllegalStateException 当前没有活动作用域时抛出
     */
    private void requireScope() {
        scopeResolver.current();
    }
}
