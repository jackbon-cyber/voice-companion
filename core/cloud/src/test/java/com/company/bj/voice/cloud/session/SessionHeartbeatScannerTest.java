package com.company.bj.voice.cloud.session;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import org.junit.jupiter.api.Test;

/**
 * 定时扫描与重路由的测试。
 *
 * <p>用**固定时钟**而非真实时间：等待真实时间流逝会让测试变慢且不稳定。
 * 这里让时钟可控，测试就能精确地验证"超时那一刻"的边界行为。
 */
class SessionHeartbeatScannerTest {

    /** 固定在某一时刻的时钟。 */
    private static final class FixedClock extends Clock {

        private final Instant instant;

        FixedClock(long epochMilli) {
            this.instant = Instant.ofEpochMilli(epochMilli);
        }

        @Override
        public ZoneOffset getZone() {
            return ZoneOffset.UTC;
        }

        @Override
        public Clock withZone(java.time.ZoneId zone) {
            return this;
        }

        @Override
        public Instant instant() {
            return instant;
        }

        @Override
        public long millis() {
            return instant.toEpochMilli();
        }
    }

    /**
     * 构造注册表。
     *
     * @param unitId 固定的处理单元
     * @return 会话注册表
     */
    private SessionRegistry registry(String unitId) {
        return new SessionRegistry(sessionId -> unitId);
    }

    @Test
    void 心跳超时的会话被扫描回收() {
        SessionRegistry registry = registry("unit-0");
        registry.register("session-1", new SessionContext("session-1", "unit-0", 1000L));

        // 阈值 5000 毫秒，当前时刻 10000：距上次心跳 9000，已超时。
        SessionHeartbeatScanner scanner =
                new SessionHeartbeatScanner(
                        registry,
                        new SessionReroutingService(registry, () -> List.of("unit-0")),
                        new FixedClock(10000L),
                        5000L);

        int reclaimed = scanner.scanExpiredSessions();

        assertThat(reclaimed).isEqualTo(1);
        assertThat(registry.find("session-1")).isEmpty();
    }

    @Test
    void 未超时的会话不被回收() {
        SessionRegistry registry = registry("unit-0");
        registry.register("session-1", new SessionContext("session-1", "unit-0", 9000L));

        SessionHeartbeatScanner scanner =
                new SessionHeartbeatScanner(
                        registry,
                        new SessionReroutingService(registry, () -> List.of("unit-0")),
                        new FixedClock(10000L),
                        5000L);

        int reclaimed = scanner.scanExpiredSessions();

        assertThat(reclaimed).isZero();
        assertThat(registry.find("session-1")).isPresent();
    }

    @Test
    void 静默时长达到超时阈值即判定超时() {
        // 边界：静默时长**恰好等于**阈值时已耗尽容忍额度，判定为超时。
        // 阈值是"最多容忍多久没心跳"的上界，不是"超过才超时"。
        SessionRegistry registry = registry("unit-0");
        registry.register("session-1", new SessionContext("session-1", "unit-0", 5000L));

        SessionHeartbeatScanner scanner =
                new SessionHeartbeatScanner(
                        registry,
                        new SessionReroutingService(registry, () -> List.of("unit-0")),
                        new FixedClock(10000L),
                        5000L);

        int reclaimed = scanner.scanExpiredSessions();

        assertThat(reclaimed).isEqualTo(1);
        assertThat(registry.find("session-1")).isEmpty();
    }

    @Test
    void 静默时长未达阈值时不算超时() {
        SessionRegistry registry = registry("unit-0");
        registry.register("session-1", new SessionContext("session-1", "unit-0", 5001L));

        SessionHeartbeatScanner scanner =
                new SessionHeartbeatScanner(
                        registry,
                        new SessionReroutingService(registry, () -> List.of("unit-0")),
                        new FixedClock(10000L),
                        5000L);

        int reclaimed = scanner.scanExpiredSessions();

        assertThat(reclaimed).isZero();
        assertThat(registry.find("session-1")).isPresent();
    }

    @Test
    void 单元失效后会话被重路由到其他单元() {
        SessionRegistry registry = registry("unit-0");
        registry.register("session-1", new SessionContext("session-1", "unit-0", 1000L));
        registry.register("session-2", new SessionContext("session-2", "unit-0", 2000L));

        SessionHeartbeatScanner scanner =
                new SessionHeartbeatScanner(
                        registry,
                        new SessionReroutingService(registry, () -> List.of("unit-0", "unit-1")),
                        new FixedClock(3000L),
                        5000L);

        int rerouted = scanner.onProcessingUnitFailed("unit-0");

        assertThat(rerouted).isEqualTo(2);
        assertThat(registry.find("session-1").get().unitId()).isEqualTo("unit-1");
        assertThat(registry.find("session-2").get().unitId()).isEqualTo("unit-1");
    }

    @Test
    void 重路由后上下文不丢失() {
        // 重路由只换执行位置，不重置对话状态。
        SessionRegistry registry = registry("unit-0");
        registry.register("session-1", new SessionContext("session-1", "unit-0", 1234L));

        SessionReroutingService service =
                new SessionReroutingService(registry, () -> List.of("unit-0", "unit-1"));

        assertThat(service.rerouteSession("session-1", "unit-0")).isTrue();

        SessionContext rebound = registry.find("session-1").orElseThrow();
        assertThat(rebound.sessionId()).isEqualTo("session-1");
        assertThat(rebound.lastHeartbeatMs()).isEqualTo(1234L);
    }

    @Test
    void 没有可用单元时保留原绑定() {
        // 没有可用单元时**不**重路由。
        // 此时把会话挪到任何地方都是错的 —— 没有可用单元意味着整个集群都不可用。
        // 保留原绑定等单元恢复，比把故障往后推要好。
        SessionRegistry registry = registry("unit-0");
        registry.register("session-1", new SessionContext("session-1", "unit-0", 1000L));

        SessionReroutingService service =
                new SessionReroutingService(registry, () -> List.of("unit-0"));

        assertThat(service.rerouteSession("session-1", "unit-0")).isFalse();
        assertThat(registry.find("session-1").get().unitId()).isEqualTo("unit-0");
    }

    @Test
    void 不会把会话挪回失效单元() {
        // 可用单元列表里若仍含失效单元，不得选它。
        SessionRegistry registry = registry("unit-0");
        registry.register("session-1", new SessionContext("session-1", "unit-0", 1000L));

        SessionReroutingService service =
                new SessionReroutingService(registry, () -> List.of("unit-0", "unit-1"));

        assertThat(service.rerouteSession("session-1", "unit-0")).isTrue();
        assertThat(registry.find("session-1").get().unitId()).isEqualTo("unit-1");
    }

    @Test
    void 失效单元上没有会话时不做任何事() {
        SessionRegistry registry = registry("unit-0");

        SessionReroutingService service =
                new SessionReroutingService(registry, () -> List.of("unit-1"));

        assertThat(service.rerouteSessionsOf("unit-0")).isZero();
    }

    @Test
    void 扫描不会误伤其它单元的会话() {
        SessionRegistry registry = new SessionRegistry(sessionId -> "unit-" + Math.abs(sessionId.hashCode() % 2));
        registry.register("session-a", new SessionContext("session-a", "unit-0", 1000L));
        registry.register("session-b", new SessionContext("session-b", "unit-1", 1000L));

        SessionHeartbeatScanner scanner =
                new SessionHeartbeatScanner(
                        registry,
                        new SessionReroutingService(registry, () -> List.of("unit-0", "unit-1")),
                        new FixedClock(10000L),
                        5000L);

        scanner.scanExpiredSessions();

        assertThat(registry.find("session-a")).isEmpty();
        assertThat(registry.find("session-b")).isEmpty();
    }
}
