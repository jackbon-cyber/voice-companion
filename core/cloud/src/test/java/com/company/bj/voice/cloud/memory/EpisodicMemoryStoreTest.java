package com.company.bj.voice.cloud.memory;

import static org.assertj.core.api.Assertions.assertThat;

import java.util.List;
import org.junit.jupiter.api.Test;

/**
 * 情景记忆的事件顺序与作用域隔离验证。
 *
 * <p>情景记忆记录「发生过什么」——一段带类型的、顺序敏感的事件序列。
 * 事件顺序必须原样保留（回放时次序本身就是信息），
 * 且情景只对记录它的作用域可见。
 */
class EpisodicMemoryStoreTest {

    @Test
    void 情景记录事件顺序与作用域() {
        ScopeResolver resolver = new ScopeResolver();
        EpisodicMemoryStore store = new EpisodicMemoryStore(resolver);
        MemoryScope scope = MemoryScope.of("t1", "u1");

        Episode episode = resolver.withScopeResult(scope,
            () -> store.record("巡检", List.of("到达现场", "读取电表", "登记结果")));

        assertThat(episode.events()).containsExactly("到达现场", "读取电表", "登记结果");
        assertThat(episode.type()).isEqualTo("巡检");
        assertThat(episode.scope()).isEqualTo(scope);
        assertThat(episode.id()).isNotBlank();
        assertThat(episode.occurredAt()).isPositive();
    }

    @Test
    void 情景在作用域内可列出() {
        ScopeResolver resolver = new ScopeResolver();
        EpisodicMemoryStore store = new EpisodicMemoryStore(resolver);
        MemoryScope first = MemoryScope.of("t1", "u1");
        MemoryScope second = MemoryScope.of("t1", "u2");

        resolver.withScopeResult(first, () -> store.record("巡检", List.of("事件一")));

        List<Episode> inFirst = resolver.withScopeResult(first, store::episodes);
        List<Episode> inSecond = resolver.withScopeResult(second, store::episodes);

        assertThat(inFirst).hasSize(1);
        assertThat(inSecond).isEmpty();
    }

    @Test
    void 按标识读取只对所属作用域可见() {
        ScopeResolver resolver = new ScopeResolver();
        EpisodicMemoryStore store = new EpisodicMemoryStore(resolver);
        MemoryScope first = MemoryScope.of("t1", "u1");
        MemoryScope second = MemoryScope.of("t1", "u2");

        Episode episode = resolver.withScopeResult(first, () -> store.record("巡检", List.of("事件一")));

        assertThat(resolver.withScopeResult(first, () -> store.episode(episode.id()))).contains(episode);
        assertThat(resolver.withScopeResult(second, () -> store.episode(episode.id()))).isEmpty();
    }
}

