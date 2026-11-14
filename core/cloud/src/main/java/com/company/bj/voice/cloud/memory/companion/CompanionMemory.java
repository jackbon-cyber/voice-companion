package com.company.bj.voice.cloud.memory.companion;

/**
 * 陪伴域记忆条目。
 *
 * <p>在通用 {@code MemoryRecord} 之上补充陪伴场景特有的三个维度：
 * <ul>
 *   <li><b>分类</b>（{@link #category}）—— 这条记忆为什么被记住；</li>
 *   <li><b>置信度</b>（{@link #confidence}）—— 抽取时有多大把握；</li>
 *   <li><b>过期时间</b>（{@link #expiresAt}）—— 时效事件的失效时刻。</li>
 * </ul>
 *
 * <p>置信度参与冲突消解：两条同类事实冲突时，置信度高的胜出。
 * 过期时间参与召回过滤：过期条目退出活跃召回集合，但仍可追溯。
 */
public record CompanionMemory(
    String id,
    String content,
    double weight,
    long createdAt,
    long expiresAt,
    double confidence,
    CompanionMemoryCategory category,
    String fingerprint,
    String scopeTenant,
    String scopeOwner,
    boolean archived) {

    /**
     * 判断该条目在给定时刻是否已过期。
     *
     * @param now 当前时间戳
     * @return 已过期返回 {@code true}
     */
    public boolean expiredAt(long now) {
        if (expiresAt <= 0L) {
            return false;
        }
        return now >= expiresAt;
    }

    /**
     * 判断该条目是否处于活跃状态（未归档且未过期）。
     *
     * @param now 当前时间戳
     * @return 处于活跃状态返回 {@code true}
     */
    public boolean activeAt(long now) {
        return !archived && !expiredAt(now);
    }
}
