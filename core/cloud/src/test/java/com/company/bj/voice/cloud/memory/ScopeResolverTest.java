package com.company.bj.voice.cloud.memory;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import org.junit.jupiter.api.Test;

/**
 * 作用域解析器的行为验证。
 *
 * <p>作用域是四层记忆的隔离边界：{@link ScopeResolver} 决定「当前操作属于哪个租户与主体」，
 * 没有它就无法保证一个主体看不到另一个主体的记忆。
 */
class ScopeResolverTest {

    @Test
    void 无作用域时读取当前作用域失败() {
        ScopeResolver resolver = new ScopeResolver();

        assertThatThrownBy(resolver::current)
            .isInstanceOf(IllegalStateException.class)
            .hasMessage("no active memory scope");
    }

    @Test
    void 作用域在执行期间可见() {
        ScopeResolver resolver = new ScopeResolver();
        MemoryScope scope = MemoryScope.of("t1", "u1");

        resolver.withScope(scope, () -> assertThat(resolver.current()).isEqualTo(scope));
    }

    @Test
    void 作用域在退出后被清除() {
        ScopeResolver resolver = new ScopeResolver();

        resolver.withScope(MemoryScope.of("t1", "u1"), () -> { });

        assertThatThrownBy(resolver::current).isInstanceOf(IllegalStateException.class);
    }

    @Test
    void 嵌套作用域在退出后恢复外层作用域() {
        ScopeResolver resolver = new ScopeResolver();
        MemoryScope outer = MemoryScope.of("t1", "u1");
        MemoryScope inner = MemoryScope.of("t2", "u2");

        resolver.withScope(outer, () -> {
            assertThat(resolver.current()).isEqualTo(outer);

            resolver.withScope(inner, () -> assertThat(resolver.current()).isEqualTo(inner));

            assertThat(resolver.current()).isEqualTo(outer);
        });
    }

    @Test
    void 有返回值的作用域执行同样支持嵌套与恢复() {
        ScopeResolver resolver = new ScopeResolver();
        MemoryScope outer = MemoryScope.of("t1", "u1");
        MemoryScope inner = MemoryScope.of("t2", "u2");

        String value = resolver.withScopeResult(outer, () -> {
            assertThat(resolver.current()).isEqualTo(outer);
            String nested = resolver.withScopeResult(inner, () -> {
                assertThat(resolver.current()).isEqualTo(inner);
                return "inner";
            });
            assertThat(nested).isEqualTo("inner");
            assertThat(resolver.current()).isEqualTo(outer);
            return "outer";
        });

        assertThat(value).isEqualTo("outer");
        assertThatThrownBy(resolver::current).isInstanceOf(IllegalStateException.class);
    }

    @Test
    void 作用域内抛异常时仍恢复原状态() {
        ScopeResolver resolver = new ScopeResolver();
        MemoryScope outer = MemoryScope.of("t1", "u1");

        assertThatThrownBy(() -> resolver.withScope(outer, () -> {
            throw new IllegalArgumentException("boom");
        })).isInstanceOf(IllegalArgumentException.class);

        assertThatThrownBy(resolver::current).isInstanceOf(IllegalStateException.class);
    }
}

