package com.company.bj.voice.cloud.memory;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * 短期记忆存储。
 *
 * <p>短期记忆保存<b>当前会话</b>的消息序列，是四层记忆里唯一<b>不做语义检索</b>的一层：
 * 它的访问模式是「按顺序追加、按序读取、按下标删除」，与长期记忆的
 * 「写入后按语义召回」是两种完全不同的访问形态，因此不共用一套抽象。
 *
 * <p>实例按<b>会话键</b>隔离：不同会话键对应不同实例，彼此的消息互不可见。
 * 短期记忆不做持久化 —— 它的语义就是「本次会话内有效」。
 */
public class ShortTermMemoryStore {

    /** 会话标识。 */
    private final String sessionKey;

    /** 消息序列，顺序即语义。 */
    private final List<String> messages = Collections.synchronizedList(new ArrayList<>());

    /**
     * 构造短期记忆存储。
     *
     * @param sessionKey 会话标识
     */
    public ShortTermMemoryStore(String sessionKey) {
        this.sessionKey = sessionKey == null ? "" : sessionKey;
    }

    /**
     * 返回会话标识。
     *
     * @return 会话标识
     */
    public String sessionKey() {
        return sessionKey;
    }

    /**
     * 追加一条消息到序列末尾。
     *
     * @param message 消息内容
     */
    public void add(String message) {
        messages.add(message);
    }

    /**
     * 读取全部消息，顺序与追加顺序一致。
     *
     * @return 消息列表的快照
     */
    public List<String> messages() {
        synchronized (messages) {
            return List.copyOf(messages);
        }
    }

    /**
     * 删除指定下标的消息。
     *
     * <p>下标越界时<b>不抛异常</b>而是安静返回：删除一条不存在的消息
     * 属于可容忍的空操作，抛异常会把调用方的正常流程打断。
     *
     * @param index 消息下标
     */
    public void deleteAt(int index) {
        synchronized (messages) {
            if (index < 0 || index >= messages.size()) {
                return;
            }
            messages.remove(index);
        }
    }

    /**
     * 清空全部消息。
     */
    public void clear() {
        messages.clear();
    }
}
