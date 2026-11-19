package com.company.bj.voice.cloud.memory;

import java.util.List;

/**
 * 带得分检索端口。
 *
 * <p><b>为什么单独开一个端口而不是给 {@link LongTermStore#search} 加返回值</b>：
 * {@code LongTermStore} 已有多个实现（Chroma 实现与四个测试假实现），
 * 直接改它的返回类型会让所有实现与调用方一起改，
 * 且"要不要得分"这个决定本不该由存储抽象强制。
 * 这里用<b>可选端口</b>的方式扩展：需要得分的调用方依赖本接口，
 * 不需要的仍依赖 {@code LongTermStore}。
 *
 * <p><b>为什么不直接返回距离而要换算成得分</b>：
 * 距离越小越相关，得分越大越相关 —— 后者更符合"置信度"的直觉，
 * 且与 {@code ChromaQueryResultReader#toScore} 用的是同一个公式，
 * 避免同一个数据在两个地方算出不同量纲的数字。
 */
public interface ScoredMemorySearch {

    /**
     * 按语义检索当前作用域下的记忆，并带上检索得分。
     *
     * @param query 查询文本
     * @param topK  返回条数上限
     * @return 带得分的命中记录，按得分<b>降序</b>排列
     * @throws IllegalStateException 当前没有活动作用域时抛出
     */
    List<ScoredMemoryRecord> searchScored(String query, int topK);
}
