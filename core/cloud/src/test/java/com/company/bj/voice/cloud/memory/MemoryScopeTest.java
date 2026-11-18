package com.company.bj.voice.cloud.memory;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import org.junit.jupiter.api.Test;

/**
 * 记忆作用域的取值语义验证。
 *
 * <p>租户与主体来自 HTTP 请求头，缺头是<b>正常</b>的调用形态，
 * 因此空白值回落缺省值而不是抛异常。
 */
class MemoryScopeTest {

    @Test
    void 缺省作用域为默认租户与默认主体() {
        MemoryScope scope = MemoryScope.of(null, null);

        assertThat(scope.tenantId()).isEqualTo("default");
        assertThat(scope.ownerKey()).isEqualTo("default");
        assertThat(scope).isEqualTo(MemoryScope.defaultScope());
    }

    @Test
    void 空白值回落到缺省值() {
        MemoryScope scope = MemoryScope.of("  ", "");

        assertThat(scope.tenantId()).isEqualTo("default");
        assertThat(scope.ownerKey()).isEqualTo("default");
    }

    @Test
    void 非空值原样保留() {
        MemoryScope scope = MemoryScope.of("tenant-a", "owner-b");

        assertThat(scope.tenantId()).isEqualTo("tenant-a");
        assertThat(scope.ownerKey()).isEqualTo("owner-b");
    }

    @Test
    void 不同作用域互不相等() {
        assertThat(MemoryScope.of("t1", "u1")).isNotEqualTo(MemoryScope.of("t1", "u2"));
        assertThat(MemoryScope.of("t1", "u1")).isNotEqualTo(MemoryScope.of("t2", "u1"));
    }

    @Test
    void 无作用域时记忆存储拒绝操作() {
        ScopeResolver resolver = new ScopeResolver();
        WorkingMemoryStore working = new WorkingMemoryStore(resolver);
        EpisodicMemoryStore episodic = new EpisodicMemoryStore(resolver);

        assertThatThrownBy(() -> working.addTask("无作用域"))
            .isInstanceOf(IllegalStateException.class)
            .hasMessage("no active memory scope");
        assertThatThrownBy(() -> episodic.record("巡检", java.util.List.of("事件")))
            .isInstanceOf(IllegalStateException.class)
            .hasMessage("no active memory scope");
    }
}

