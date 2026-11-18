package com.company.bj.voice.cloud.memory;

import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 会话归属的用户标识注册表。
 *
 * <p>把「这个会话属于哪个用户」这件事从散落的调用点收拢到一处，
 * 使记忆作用域的来源是**唯一且可查的**。
 *
 * <p><b>为什么需要它</b>：记忆作用域由 {@link ScopeResolver} 从当前执行上下文解析，
 * 而 {@code ScopeResolver} 用 {@code ThreadLocal} 实现 ——
 * 跨线程不可见。云端的 WebSocket 消息处理与 HTTP 请求处理往往不在同一个线程上，
 * 因此「当前线程是谁」这件事必须能被显式地绑定与查询，
 * 否则记忆读写要么找不到作用域（抛异常），要么退化成默认作用域（读到别人的数据）。
 *
 * <p><b>为什么不用 HTTP 请求头</b>：上行通道是 WebSocket，
 * 握手之后的每一条消息都不再携带 HTTP 头。
 * 把用户标识放进协议消息（{@code session.ownerKey}）是唯一在整条链路上都拿得到的方式。
 */
public class SessionOwnerRegistry {

    /** 会话标识到用户标识的映射。 */
    private final ConcurrentHashMap<String, String> ownerBySession = new ConcurrentHashMap<>();

    /** 缺省租户标识。与 {@link MemoryScope#DEFAULT_TENANT_ID} 一致。 */
    private final String defaultTenantId;

    /**
     * 构造注册表。
     *
     * @param defaultTenantId 缺省租户标识，不能为 null 或空白
     * @throws IllegalArgumentException 参数非法时抛出
     */
    public SessionOwnerRegistry(String defaultTenantId) {
        if (defaultTenantId == null || defaultTenantId.isBlank()) {
            throw new IllegalArgumentException("defaultTenantId must not be blank");
        }
        this.defaultTenantId = defaultTenantId;
    }

    /**
     * 登记会话归属的用户。
     *
     * @param sessionId 会话标识
     * @param ownerKey  用户标识
     * @throws IllegalArgumentException 参数非法时抛出
     */
    public void bind(String sessionId, String ownerKey) {
        if (sessionId == null || sessionId.isBlank()) {
            throw new IllegalArgumentException("sessionId must not be blank");
        }
        if (ownerKey == null || ownerKey.isBlank()) {
            throw new IllegalArgumentException("ownerKey must not be blank");
        }
        ownerBySession.put(sessionId, ownerKey);
    }

    /**
     * 解除会话的用户绑定。
     *
     * <p>会话结束时必须解绑：绑定残留会让**下一个复用同一会话标识**的会话
     * 继承前一个用户的身份，从而读到前一个用户的记忆 ——
     * 这是一种极难复现的越权泄漏。
     *
     * @param sessionId 会话标识
     */
    public void unbind(String sessionId) {
        if (sessionId != null) {
            ownerBySession.remove(sessionId);
        }
    }

    /**
     * 查询会话归属的用户标识。
     *
     * @param sessionId 会话标识
     * @return 用户标识；未登记时为空
     */
    public Optional<String> ownerOf(String sessionId) {
        if (sessionId == null) {
            return Optional.empty();
        }
        return Optional.ofNullable(ownerBySession.get(sessionId));
    }

    /**
     * 解析会话对应的记忆作用域。
     *
     * <p>会话未登记用户标识时**退化为缺省作用域**，而不是抛异常：
     * 未携带用户标识的接入（例如尚未接入账号体系的老设备）
     * 仍应能正常对话，只是它的记忆不与其他用户共享。
     *
     * <p><b>这与「无活动作用域时抛异常」不矛盾</b>：
     * 那条规则防的是「调用方忘了设作用域」，
     * 而这里是「确实没有用户标识」这一合法的业务形态。
     *
     * @param sessionId 会话标识
     * @return 记忆作用域
     */
    public MemoryScope scopeOf(String sessionId) {
        return ownerOf(sessionId)
                .map(owner -> MemoryScope.of(defaultTenantId, owner))
                .orElseGet(MemoryScope::defaultScope);
    }

    /**
     * 查询当前登记的会话数量。
     *
     * @return 数量
     */
    public int size() {
        return ownerBySession.size();
    }
}
