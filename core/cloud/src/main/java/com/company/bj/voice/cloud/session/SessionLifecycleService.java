package com.company.bj.voice.cloud.session;

import com.company.bj.voice.cloud.memory.MemoryScope;
import com.company.bj.voice.cloud.memory.SessionOwnerRegistry;
import com.company.bj.voice.cloud.protocol.ProtocolValidator;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Clock;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

/**
 * 会话生命周期服务。
 *
 * <p>把上行协议消息翻译成 {@link SessionRegistry} 上的注册/回收动作。
 * 有了这一层，云端的会话注册表才真正被接线 —— 此前 {@code register()}
 * 与 {@code onHeartbeatTimeout()} 没有任何调用方，会话状态实际处于孤岛。
 *
 * <p>本类属于 Service 层，只依赖 {@link SessionRegistry} 与
 * {@link ProtocolValidator}，不依赖任何 Repository。
 *
 * <p><b>会话归属</b>：会话开始消息携带的 {@code ownerKey} 决定该会话的用户身份，
 * 记忆作用域由它推导。没有它，云端写的记忆全部落进同一个作用域，
 * 「不同用户互不可见」就不成立。
 */
@Service
public class SessionLifecycleService {

    /** 日志器。 */
    private static final Logger LOGGER = LoggerFactory.getLogger(SessionLifecycleService.class);

    /** 会话注册表。 */
    private final SessionRegistry sessionRegistry;

    /** 协议校验器。 */
    private final ProtocolValidator protocolValidator;

    /** 会话归属注册表。 */
    private final SessionOwnerRegistry ownerRegistry;

    /** JSON 解析器。 */
    private final ObjectMapper objectMapper;

    /** 时钟。注入而非直接取系统时间，便于测试。 */
    private final Clock clock;

    /**
     * 构造会话生命周期服务。
     *
     * @param sessionRegistry 会话注册表
     * @param protocolValidator 协议校验器
     * @param ownerRegistry 会话归属注册表
     */
    @Autowired
    public SessionLifecycleService(
            SessionRegistry sessionRegistry,
            ProtocolValidator protocolValidator,
            SessionOwnerRegistry ownerRegistry) {
        this(sessionRegistry, protocolValidator, ownerRegistry, Clock.systemUTC());
    }

    /**
     * 构造会话生命周期服务。
     *
     * @param sessionRegistry 会话注册表
     * @param protocolValidator 协议校验器
     * @param ownerRegistry 会话归属注册表
     * @param clock 时钟
     */
    public SessionLifecycleService(
            SessionRegistry sessionRegistry,
            ProtocolValidator protocolValidator,
            SessionOwnerRegistry ownerRegistry,
            Clock clock) {
        this.sessionRegistry = sessionRegistry;
        this.protocolValidator = protocolValidator;
        this.ownerRegistry = ownerRegistry;
        this.clock = clock;
        this.objectMapper = new ObjectMapper();
    }

    /**
     * 处理会话开始消息：注册会话并绑定处理单元。
     *
     * @param sessionId 会话标识
     * @param ownerKey  会话归属的用户标识；为空时使用缺省作用域
     * @return 该会话绑定的处理单元标识
     * @throws SessionRoutingException 会话标识为空时抛出
     */
    public String onSessionBegin(String sessionId, String ownerKey) {
        String unitId = sessionRegistry.resolveUnit(sessionId);
        sessionRegistry.register(
                sessionId, new SessionContext(sessionId, unitId, clock.millis()));
        if (ownerKey != null && !ownerKey.isBlank()) {
            ownerRegistry.bind(sessionId, ownerKey);
        }
        LOGGER.info("会话已注册：{} → 处理单元 {}，用户={}", sessionId, unitId,
                ownerKey == null || ownerKey.isBlank() ? "缺省" : ownerKey);
        return unitId;
    }

    /**
     * 处理心跳消息：刷新会话时间戳。
     *
     * <p>心跳**不**注册未知会话 —— 只有走过 {@code begin} 的会话才是活会话。
     * 让心跳隐式创建会话会让一个乱发的 keepalive 伪造出会话，占住处理单元。
     *
     * @param sessionId 会话标识
     */
    public void onKeepalive(String sessionId) {
        SessionContext existing = sessionRegistry.find(sessionId).orElse(null);
        if (existing == null) {
            return;
        }
        sessionRegistry.register(
                sessionId,
                new SessionContext(existing.sessionId(), existing.unitId(), clock.millis()));
    }

    /**
     * 处理会话结束消息：回收会话。
     *
     * <p>同时解除用户绑定：绑定残留会让下一个复用同一会话标识的会话
     * 继承前一个用户的身份，从而读到前一个用户的记忆。
     *
     * @param sessionId 会话标识
     * @param reason 结束原因
     */
    public void onSessionEnd(String sessionId, String reason) {
        sessionRegistry.remove(sessionId);
        ownerRegistry.unbind(sessionId);
        LOGGER.info("会话已回收：{}（原因：{}）", sessionId, reason);
    }

    /**
     * 解析会话对应的记忆作用域。
     *
     * @param sessionId 会话标识
     * @return 记忆作用域
     */
    public MemoryScope scopeOf(String sessionId) {
        return ownerRegistry.scopeOf(sessionId);
    }

    /**
     * 处理心跳超时：回收会话。
     *
     * @param sessionId 会话标识
     */
    public void onHeartbeatTimeout(String sessionId) {
        sessionRegistry.onHeartbeatTimeout(sessionId);
        ownerRegistry.unbind(sessionId);
    }

    /**
     * 处理一条上行消息。
     *
     * <p>消息形态按协议分流：会话生命周期消息影响注册表，
     * 音频帧与意图报告不影响（它们由后续阶段的推理链路消费）。
     *
     * <p>协议不合法的消息**静默忽略**而不是抛异常：一条坏消息不该让
     * 整条 WebSocket 连接断开 —— 断开会让设备重连，而重连会丢掉
     * 已经积累的会话上下文。
     *
     * @param payload 上行消息 JSON 文本
     */
    public void onUplinkMessage(String payload) {
        JsonNode node;
        try {
            node = objectMapper.readTree(payload);
        } catch (JsonProcessingException error) {
            LOGGER.warn("上行消息不是合法 JSON，已忽略：{}", error.getOriginalMessage());
            return;
        }

        if (!dispatchSessionMessage(node)) {
            LOGGER.debug("上行消息不是会话生命周期消息，已忽略");
        }
    }

    private boolean dispatchSessionMessage(JsonNode node) {
        String schemaName = classifySchema(node);
        if (schemaName == null) {
            return false;
        }
        List<String> errors = protocolValidator.validate(schemaName, payloadOf(node));
        if (!errors.isEmpty()) {
            LOGGER.warn("上行会话消息不符合协议，已忽略：{}", errors.get(0));
            return true;
        }

        String sessionId = node.path("sessionId").asText();
        String type = node.path("type").asText();
        switch (type) {
            case "begin" -> onSessionBegin(sessionId, node.path("ownerKey").asText(""));
            case "keepalive" -> onKeepalive(sessionId);
            case "end" -> onSessionEnd(sessionId, node.path("reason").asText(""));
            default -> LOGGER.debug("未知的会话消息类型：{}", type);
        }
        return true;
    }

    /**
     * 判断一条消息属于哪份 schema。
     *
     * @param node 消息节点
     * @return schema 名；不是协议消息时返回 null
     */
    private String classifySchema(JsonNode node) {
        if (node.hasNonNull("type") && node.hasNonNull("sessionId")) {
            return "session";
        }
        if (node.hasNonNull("intent")) {
            return "intent-report";
        }
        if (node.hasNonNull("payloadBase64")) {
            return "audio-frame";
        }
        return null;
    }

    private String payloadOf(JsonNode node) {
        try {
            return objectMapper.writeValueAsString(node);
        } catch (JsonProcessingException error) {
            return "{}";
        }
    }
}
