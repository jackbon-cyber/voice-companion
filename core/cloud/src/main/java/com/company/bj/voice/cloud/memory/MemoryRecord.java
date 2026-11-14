package com.company.bj.voice.cloud.memory;

/**
 * 长期记忆记录。
 *
 * <p>一条长期记忆 = 一段文本 + 一组权重与时间戳 + 归属作用域 + 归档标记。
 *
 * <p><b>归档标记</b>（{@code archived}）表达的是「软删除」：
 * 遗忘操作不物理删除记录，只把 {@code archived} 置为 {@code true}。
 * 这样做的收益是记录<b>仍可被追溯与恢复</b>（合规审计、误删找回），
 * 而检索时通过 {@code where} 过滤掉归档记录，用户感知上与删除无异。
 *
 * @param id        记录标识
 * @param content   记录正文
 * @param weight    权重，影响检索排序
 * @param createdAt 创建时间戳（epoch 毫秒）
 * @param scope     归属作用域
 * @param archived  是否已归档（软删除）
 */
public record MemoryRecord(
    String id,
    String content,
    double weight,
    long createdAt,
    MemoryScope scope,
    boolean archived) {
}
