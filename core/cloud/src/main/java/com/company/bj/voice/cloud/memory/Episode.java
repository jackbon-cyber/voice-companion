package com.company.bj.voice.cloud.memory;

import java.util.List;

/**
 * 情景记忆条目。
 *
 * <p>情景记忆记录「发生过什么」——一段带类型、顺序敏感的<b>事件序列</b>。
 * 事件顺序本身就是信息（回放时次序有意义），因此事件以列表原样保存，
 * 不做去重、不做重排。
 *
 * @param id         情景标识
 * @param type       情景类型，例如「巡检」
 * @param events     事件序列，顺序敏感
 * @param occurredAt 发生时间戳（epoch 毫秒）
 * @param scope      归属作用域
 */
public record Episode(
    String id,
    String type,
    List<String> events,
    long occurredAt,
    MemoryScope scope) {

    /**
     * 规范化构造：事件列表拷贝为不可变列表，防止调用方事后改写。
     *
     * @param id         情景标识
     * @param type       情景类型
     * @param events     事件序列
     * @param occurredAt 发生时间戳
     * @param scope      归属作用域
     */
    public Episode {
        events = events == null ? List.of() : List.copyOf(events);
    }
}
