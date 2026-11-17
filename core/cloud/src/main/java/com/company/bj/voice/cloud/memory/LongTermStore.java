package com.company.bj.voice.cloud.memory;

import java.util.List;
import java.util.Optional;

/**
 * 长期记忆存储端口。
 *
 * <p><b>本接口不接受作用域入参</b>：作用域一律由 {@link ScopeResolver}
 * 从当前执行上下文解析。理由是把作用域做成入参，调用方就可能在某个调用点
 * 「忘了传」或「传错」，而作用域是越权读写的唯一屏障 —— 屏障不该由调用方负责维护。
 *
 * <p>所有实现都必须在<b>没有活动作用域</b>时拒绝操作（抛
 * {@link IllegalStateException}），而不是退化成某个全局默认作用域。
 */
public interface LongTermStore {

    /**
     * 写入一条长期记忆，使用默认权重。
     *
     * @param content 记录正文
     * @return 写入后的记录
     * @throws IllegalStateException 当前没有活动作用域时抛出
     */
    MemoryRecord remember(String content);

    /**
     * 写入一条长期记忆并指定权重。
     *
     * @param content 记录正文
     * @param weight  权重，影响检索排序
     * @return 写入后的记录
     * @throws IllegalStateException 当前没有活动作用域时抛出
     */
    MemoryRecord remember(String content, double weight);

    /**
     * 按标识读取一条长期记忆。
     *
     * <p>记录不属于当前作用域、或已被归档时，返回空。
     *
     * @param id 记录标识
     * @return 记录，不可见时为空
     * @throws IllegalStateException 当前没有活动作用域时抛出
     */
    Optional<MemoryRecord> find(String id);

    /**
     * 按语义检索当前作用域下的<b>未归档</b>长期记忆。
     *
     * @param query 查询文本
     * @param topK  返回条数上限
     * @return 命中的记录列表，按相似度降序
     * @throws IllegalStateException 当前没有活动作用域时抛出
     */
    List<MemoryRecord> search(String query, int topK);

    /**
     * 列出当前作用域下的<b>未归档</b>长期记忆。
     *
     * <p>与 {@link #search} 的区别：检索需要查询文本并按<b>语义相关度</b>排序，
     * 而列举只需要"把本作用域的记录都拿出来看一遍"——
     * 控制台的记忆浏览面板要的是后者。为此单独提供本方法，
     * 而不是让调用方用一个无意义的查询词去调用 {@code search} ——
     * 那不仅会引入一次无谓的嵌入调用，还会让返回结果被语义相关度裁剪，
     * 看不到与查询词无关的记录。
     *
     * <p><b>作用域过滤与归档过滤都由存储层施加</b>，调用方无法绕过。
     *
     * @param topK 返回条数上限
     * @return 记录列表，按创建时间<b>降序</b>排列（最新的在前）
     * @throws IllegalStateException 当前没有活动作用域时抛出
     */
    List<MemoryRecord> list(int topK);

    /**
     * 遗忘一条长期记忆（软删除）。
     *
     * @param id 记录标识
     * @return 是否遗忘成功
     * @throws IllegalStateException 当前没有活动作用域时抛出
     */
    boolean forget(String id);

    /**
     * 列出当前作用域下的<b>已归档</b>长期记忆。
     *
     * @param topK 返回条数上限
     * @return 归档记录列表
     * @throws IllegalStateException 当前没有活动作用域时抛出
     */
    List<MemoryRecord> archived(int topK);

    /**
     * 清除当前作用域下的<b>全部</b>长期记忆（含已归档记录），返回被清除的记录数。
     *
     * <p><b>为什么需要这个方法</b>：某些场景（如评测）会反复向记忆库写入
     * 一次性数据，而检索的 {@code topK} 名额是<b>有限</b>的 ——
     * 上一轮遗留的记录会挤占本轮的召回名额，让实测值随运行次数漂移。
     * 这类场景必须能在开始前把状态归零，否则指标不可复现。
     *
     * <p><b>作用域隔离在存储层强制</b>：本方法只清除当前作用域的记录，
     * 绝不会影响其他租户/主体的数据。
     *
     * <p><b>物理删除而非软删除</b>：调用方的意图是"让状态回到初始"，
     * 保留归档记录会让记录总数持续增长，还要额外依赖过滤条件才能真正归零。
     *
     * @return 被清除的记录数
     * @throws IllegalStateException 当前没有活动作用域时抛出
     */
    int clearCurrentScope();

    /**
     * 把多条长期记忆归并为一条新记录。
     *
     * <p>归并必须<b>保留全部原文</b>：归并的目的是压缩条目数量，
     * 而不是丢弃信息。原文丢失的归并等于数据损坏。
     *
     * @param ids 待归并的记录标识列表
     * @return 归并产生的新记录
     * @throws IllegalStateException 当前没有活动作用域时抛出
     */
    Optional<MemoryRecord> consolidate(List<String> ids);
}
