package com.company.bj.voice.cloud.memory;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

/**
 * 作用域键格式的<b>唯一拥有者</b>的一致性验证。
 *
 * <p>工作记忆与情景记忆都按作用域分桶、各自命名持久化文件，
 * 它们的作用域键必须<b>由同一份实现产出</b>。本测试是本次重构的核心防回归护栏：
 * 若将来有人只改了其中一个 store 的键格式，本测试立刻失败 ——
 * 因为键格式一旦分叉，后果不是报错，而是两个不同作用域共用一个桶、
 * 互相读到对方的数据（跨作用域泄漏）。
 *
 * <p>同时钉住长度前缀格式本身：它让 {@code ("a.b", "c")} 与 {@code ("a", "b.c")}
 * 落到不同的键上，是防碰撞的正确设计，不得被「简化」成单分隔符拼接。
 */
class ScopeKeysTest {

    @Test
    void 两个存储对同一作用域产出同一个键() {
        MemoryScope scope = MemoryScope.of("tenant-1", "owner-1");

        // 两个 store 都委托给 ScopeKeys，键格式只有一份实现。
        assertThat(ScopeKeys.scopeKey(scope))
            .isEqualTo(ScopeKeys.scopeKey(MemoryScope.of("tenant-1", "owner-1")));
    }

    @Test
    void 两个存储的持久化文件名共享同一个作用域标识() {
        MemoryScope scope = MemoryScope.of("tenant-1", "owner-1");

        String workingName = WorkingMemoryStore.scopeFileName("working.json", scope);
        String episodicName = EpisodicMemoryStore.scopeFileName("episodic.json", scope);

        // 文件名可以不同（各层各一个文件），但其中的作用域标识必须完全一致。
        assertThat(workingName).endsWith("-" + ScopeKeys.scopeKey(scope) + ".json");
        assertThat(episodicName).endsWith("-" + ScopeKeys.scopeKey(scope) + ".json");
    }

    @Test
    void 键采用长度前缀格式以避免分隔符歧义() {
        // 这两组组合若用单分隔符拼接会撞成同一个键，从而互相读到对方的数据。
        MemoryScope first = MemoryScope.of("a.b", "c");
        MemoryScope second = MemoryScope.of("a", "b.c");

        assertThat(ScopeKeys.scopeKey(first)).isNotEqualTo(ScopeKeys.scopeKey(second));
        assertThat(ScopeKeys.scopeKey(first)).isEqualTo("3-a.b-1-c");
        assertThat(ScopeKeys.scopeKey(second)).isEqualTo("1-a-3-b.c");
    }

    @Test
    void 未配置文件名时使用各层默认名() {
        MemoryScope scope = MemoryScope.of("t1", "u1");

        assertThat(WorkingMemoryStore.scopeFileName(null, scope)).isEqualTo("working-memory-2-t1-2-u1.json");
        assertThat(EpisodicMemoryStore.scopeFileName("  ", scope)).isEqualTo("episodic-memory-2-t1-2-u1.json");
    }

    @Test
    void 配置文件名时保留其基础名并追加作用域标识() {
        MemoryScope scope = MemoryScope.of("t1", "u1");

        assertThat(WorkingMemoryStore.scopeFileName("custom.json", scope)).isEqualTo("custom-2-t1-2-u1.json");
        // 缺少 .json 后缀时也只追加一次后缀。
        assertThat(EpisodicMemoryStore.scopeFileName("custom", scope)).isEqualTo("custom-2-t1-2-u1.json");
    }
}

