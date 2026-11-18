package com.company.bj.voice.cloud.session;

import static org.assertj.core.api.Assertions.assertThat;

import com.company.bj.voice.cloud.memory.MemoryScope;
import com.company.bj.voice.cloud.memory.SessionOwnerRegistry;
import com.company.bj.voice.cloud.protocol.ProtocolValidator;
import java.nio.file.Path;
import java.util.Optional;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class SessionLifecycleServiceTest {

    /** 协议 schema 所在目录。 */
    private static final Path SCHEMA_DIR = Path.of("..", "protocol", "schema");

    private SessionRegistry registry;
    private SessionOwnerRegistry ownerRegistry;
    private SessionLifecycleService service;

    @BeforeEach
    void setUp() {
        registry = new SessionRegistry(sessionId -> "unit-1");
        ownerRegistry = new SessionOwnerRegistry(MemoryScope.DEFAULT_TENANT_ID);
        service = new SessionLifecycleService(
                registry, new ProtocolValidator(SCHEMA_DIR), ownerRegistry);
    }

    @Test
    void 会话开始时注册会话() {
        service.onSessionBegin("session-1", "user-a");

        Optional<SessionContext> context = registry.find("session-1");
        assertThat(context).isPresent();
        assertThat(context.get().unitId()).isEqualTo("unit-1");
    }

    @Test
    void 会话开始时绑定用户标识() {
        service.onSessionBegin("session-1", "user-a");

        assertThat(ownerRegistry.ownerOf("session-1")).contains("user-a");
        assertThat(service.scopeOf("session-1"))
                .isEqualTo(MemoryScope.of(MemoryScope.DEFAULT_TENANT_ID, "user-a"));
    }

    @Test
    void 未携带用户标识时退化为缺省作用域() {
        service.onSessionBegin("session-1", "");

        // 缺省作用域是合法形态：未接入账号体系的设备仍应能正常对话，
        // 只是它的记忆不与其他用户共享。
        assertThat(ownerRegistry.ownerOf("session-1")).isEmpty();
        assertThat(service.scopeOf("session-1")).isEqualTo(MemoryScope.defaultScope());
    }

    @Test
    void 心跳更新会话时间戳且不回收() {
        service.onSessionBegin("session-1", "user-a");
        service.onKeepalive("session-1");

        assertThat(registry.find("session-1")).isPresent();
    }

    @Test
    void 会话结束时回收会话() {
        service.onSessionBegin("session-1", "user-a");
        service.onSessionEnd("session-1", "user_exit");

        assertThat(registry.find("session-1")).isEmpty();
    }

    @Test
    void 会话结束时解除用户绑定() {
        service.onSessionBegin("session-1", "user-a");
        service.onSessionEnd("session-1", "user_exit");

        // 绑定残留会让下一个复用同一会话标识的会话继承前一个用户的身份，
        // 从而读到前一个用户的记忆 —— 极难复现的越权泄漏。
        assertThat(ownerRegistry.ownerOf("session-1")).isEmpty();
    }

    @Test
    void 未知会话的结束消息不抛异常() {
        service.onSessionEnd("not-exists", "user_exit");

        assertThat(registry.find("not-exists")).isEmpty();
    }

    @Test
    void 路由单元与会话注册表一致() {
        service.onSessionBegin("session-1", "user-a");

        assertThat(registry.resolveUnit("session-1")).isEqualTo("unit-1");
    }

    @Test
    void 上行begin消息注册会话() {
        service.onUplinkMessage("{\"sessionId\":\"s-1\",\"type\":\"begin\"}");

        assertThat(registry.find("s-1")).isPresent();
    }

    @Test
    void 上行begin消息携带用户标识时绑定用户() {
        service.onUplinkMessage(
                "{\"sessionId\":\"s-1\",\"type\":\"begin\",\"ownerKey\":\"user-a\"}");

        assertThat(ownerRegistry.ownerOf("s-1")).contains("user-a");
    }

    @Test
    void 上行keepalive消息不新建会话() {
        service.onUplinkMessage("{\"sessionId\":\"s-2\",\"type\":\"keepalive\"}");

        assertThat(registry.find("s-2")).isEmpty();
    }

    @Test
    void 上行end消息回收会话() {
        service.onUplinkMessage("{\"sessionId\":\"s-3\",\"type\":\"begin\"}");
        service.onUplinkMessage("{\"sessionId\":\"s-3\",\"type\":\"end\",\"reason\":\"user_exit\"}");

        assertThat(registry.find("s-3")).isEmpty();
    }

    @Test
    void 协议不合法的会话消息被忽略() {
        service.onUplinkMessage("{\"sessionId\":\"s-4\",\"type\":\"started\"}");

        assertThat(registry.find("s-4")).isEmpty();
    }

    @Test
    void 非法JSON不抛出异常() {
        service.onUplinkMessage("{not json");

        assertThat(registry.size()).isZero();
    }

    @Test
    void 音频帧消息不改变会话注册状态() {
        service.onUplinkMessage(
                "{\"sessionId\":\"s-5\",\"sequence\":0,\"timestampMs\":0,"
                        + "\"sampleRate\":16000,\"payloadBase64\":\"AAA=\"}");

        assertThat(registry.find("s-5")).isEmpty();
    }

    @Test
    void 意图报告消息不改变会话注册状态() {
        service.onUplinkMessage(
                "{\"sessionId\":\"s-6\",\"sequence\":0,\"intent\":\"play_music\","
                        + "\"confidence\":0.9,\"handledLocally\":true}");

        assertThat(registry.find("s-6")).isEmpty();
    }

    @Test
    void 意图报告携带原话时通过协议校验() {
        // 意图报告带 text 是协议的一部分，携带原话的消息必须通过校验 ——
        // 否则云端会因为"多了一个字段"而忽略整条消息，
        // 记忆永远写不进去，且不会报任何错。
        service.onUplinkMessage(
                "{\"sessionId\":\"s-7\",\"sequence\":0,\"intent\":\"chat\","
                        + "\"confidence\":0.9,\"handledLocally\":false,"
                        + "\"text\":\"我妈妈叫李芳\"}");

        assertThat(registry.find("s-7")).isEmpty();
    }
}
