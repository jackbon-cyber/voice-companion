package com.company.bj.voice.cloud.memory;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

/**
 * 短期记忆的追加、删除与清空行为验证。
 *
 * <p>短期记忆保存当前会话的消息序列，语义上是一条<b>有序</b>的消息列表，
 * 因此追加保持顺序、删除按<b>下标</b>而非标识进行。
 */
class ShortTermMemoryStoreTest {

    @Test
    void 追加后按原顺序读取() {
        ShortTermMemoryStore store = new ShortTermMemoryStore("session-1");

        store.add("第一条");
        store.add("第二条");
        store.add("第三条");

        assertThat(store.messages()).containsExactly("第一条", "第二条", "第三条");
    }

    @Test
    void 删除指定下标后其余消息保留原顺序() {
        ShortTermMemoryStore store = new ShortTermMemoryStore("session-1");
        store.add("第一条");
        store.add("第二条");
        store.add("第三条");

        store.deleteAt(1);

        assertThat(store.messages()).containsExactly("第一条", "第三条");
    }

    @Test
    void 清空后不含任何消息() {
        ShortTermMemoryStore store = new ShortTermMemoryStore("session-1");
        store.add("第一条");
        store.add("第二条");

        store.clear();

        assertThat(store.messages()).isEmpty();
    }

    @Test
    void 不同会话键的消息互不可见() {
        ShortTermMemoryStore first = new ShortTermMemoryStore("session-1");
        ShortTermMemoryStore second = new ShortTermMemoryStore("session-2");

        first.add("只属于会话一");

        assertThat(first.messages()).containsExactly("只属于会话一");
        assertThat(second.messages()).isEmpty();
    }
}

