package com.company.bj.voice.cloud.session;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class SessionRegistryTest {

    @Test
    void 同一会话始终解析到同一处理单元() {
        SessionRegistry registry =
                new SessionRegistry(sessionId -> "unit-" + Math.abs(sessionId.hashCode() % 3));
        String first = registry.resolveUnit("session-1");
        for (int i = 0; i < 10; i++) {
            assertThat(registry.resolveUnit("session-1")).isEqualTo(first);
        }
    }

    @Test
    void 心跳超时后会话被回收() {
        SessionRegistry registry = new SessionRegistry(sessionId -> "unit-1");
        registry.register("session-1", new SessionContext("session-1", "unit-1", 0L));
        registry.onHeartbeatTimeout("session-1");
        assertThat(registry.find("session-1")).isEmpty();
    }

    @Test
    void 注册后可查到会话上下文() {
        SessionRegistry registry = new SessionRegistry(sessionId -> "unit-1");
        registry.register("session-1", new SessionContext("session-1", "unit-1", 100L));

        assertThat(registry.find("session-1")).isPresent();
        assertThat(registry.find("session-1").get().unitId()).isEqualTo("unit-1");
        assertThat(registry.find("session-2")).isEmpty();
    }

    @Test
    void 重复注册同一会话会覆盖旧上下文() {
        SessionRegistry registry = new SessionRegistry(sessionId -> "unit-1");
        registry.register("session-1", new SessionContext("session-1", "unit-1", 100L));
        registry.register("session-1", new SessionContext("session-1", "unit-2", 200L));

        assertThat(registry.find("session-1").get().unitId()).isEqualTo("unit-2");
    }

    @Test
    void 移除不存在的会话不抛异常() {
        SessionRegistry registry = new SessionRegistry(sessionId -> "unit-1");
        registry.remove("not-exists");
        assertThat(registry.find("not-exists")).isEmpty();
    }
}
