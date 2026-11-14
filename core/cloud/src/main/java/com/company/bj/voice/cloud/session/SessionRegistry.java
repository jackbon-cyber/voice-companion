package com.company.bj.voice.cloud.session;

import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.function.Function;

/**
 * 会话注册表与会话粘滞路由。
 *
 * <p><b>粘滞的含义</b>：同一会话在整个生命周期内必须落在同一个处理单元上。
 * 会话状态（对话上下文、已装配的记忆、进行中的流式回复）都在那个单元的内存里；
 * 会话漂到别的单元，之前的上下文就接不上了，用户会感到"机器人失忆"。
 *
 * <p><b>为什么不自己实现哈希</b>：处理单元的分配策略是部署决策 ——
 * 一致性哈希、虚拟节点、还是固定分片，取决于处理单元的数量与扩缩容方式。
 * 本类只负责"给定会话标识，算出它属于哪个单元"，把策略作为函数注入，
 * 部署时才决定具体实现。
 *
 * <p>本类属于 Service 层，不依赖任何 Repository；持久化留待后续阶段。
 */
public class SessionRegistry {

    /** 会话标识到上下文的映射。 */
    private final ConcurrentHashMap<String, SessionContext> sessions = new ConcurrentHashMap<>();

    /** 会话到处理单元的映射策略，由部署方注入。 */
    private final Function<String, String> unitResolver;

    /**
     * 构造会话注册表。
     *
     * @param unitResolver 会话到处理单元的映射策略，不能为 null
     * @throws IllegalArgumentException {@code unitResolver} 为 null 时抛出
     */
    public SessionRegistry(Function<String, String> unitResolver) {
        if (unitResolver == null) {
            throw new IllegalArgumentException("unitResolver must not be null");
        }
        this.unitResolver = unitResolver;
    }

    /**
     * 注册一个会话。
     *
     * <p>重复注册同一会话会覆盖旧上下文 —— 端侧重连后带着同一个会话标识回来时，
     * 应当以新上下文为准，而不是保留可能已过期的旧状态。
     *
     * @param sessionId 会话标识
     * @param context 会话上下文
     * @return 该会话绑定的处理单元标识
     * @throws IllegalArgumentException 参数为 null 时抛出
     */
    public String register(String sessionId, SessionContext context) {
        if (sessionId == null || context == null) {
            throw new IllegalArgumentException("sessionId and context must not be null");
        }
        sessions.put(sessionId, context);
        return context.unitId();
    }

    /**
     * 查找会话上下文。
     *
     * @param sessionId 会话标识
     * @return 会话上下文；会话不存在时返回空
     */
    public Optional<SessionContext> find(String sessionId) {
        if (sessionId == null) {
            return Optional.empty();
        }
        return Optional.ofNullable(sessions.get(sessionId));
    }

    /**
     * 移除一个会话。
     *
     * @param sessionId 会话标识
     */
    public void remove(String sessionId) {
        if (sessionId != null) {
            sessions.remove(sessionId);
        }
    }

    /**
     * 找出心跳超时的会话。
     *
     * <p>用 {@code lastHeartbeatMs + timeoutMs <= nowMs} 判定，
     * 即**静默时长达到**超时阈值就算超时。
     *
     * <p>取"达到"而非"超过"，与超时阈值的通行语义一致：
     * 阈值就是"最多容忍多久没有心跳"的**上界**，
     * 恰好等于上界的会话已经耗尽了容忍额度。
     *
     * @param nowMs 当前时刻（毫秒）
     * @param timeoutMs 超时阈值（毫秒）
     * @return 超时的会话上下文列表
     */
    public List<SessionContext> findExpired(long nowMs, long timeoutMs) {
        List<SessionContext> expired = new ArrayList<>();
        for (SessionContext context : sessions.values()) {
            if (context.lastHeartbeatMs() + timeoutMs <= nowMs) {
                expired.add(context);
            }
        }
        return expired;
    }

    /**
     * 找出绑定到指定处理单元的会话。
     *
     * <p>处理单元失效时，需要把该单元上所有会话重路由走。
     * 没有这个查询，重路由就只能靠遍历全表比对单元标识。
     *
     * @param unitId 处理单元标识
     * @return 该单元上的会话上下文列表
     */
    public List<SessionContext> findByUnit(String unitId) {
        if (unitId == null) {
            return List.of();
        }
        List<SessionContext> matched = new ArrayList<>();
        for (SessionContext context : sessions.values()) {
            if (unitId.equals(context.unitId())) {
                matched.add(context);
            }
        }
        return matched;
    }

    /**
     * 把会话重新绑定到另一个处理单元。
     *
     * <p>**上下文不丢失**：会话标识与最近心跳时间都保留。
     * 重路由的目的只是换一个执行位置，不是重置对话 ——
     * 丢掉上下文会让用户感到"机器人失忆"。
     *
     * @param sessionId 会话标识
     * @param newUnitId 新的处理单元标识
     * @return 重新绑定后的会话上下文
     * @throws IllegalArgumentException 会话不存在或新单元标识为 null 时抛出
     */
    public SessionContext rebind(String sessionId, String newUnitId) {
        SessionContext existing = sessions.get(sessionId);
        if (existing == null) {
            throw new IllegalArgumentException("会话不存在：" + sessionId);
        }
        if (newUnitId == null) {
            throw new IllegalArgumentException("newUnitId must not be null");
        }
        SessionContext rebound = new SessionContext(existing.sessionId(), newUnitId, existing.lastHeartbeatMs());
        sessions.put(sessionId, rebound);
        return rebound;
    }

    /**
     * 解析会话所属的处理单元。
     *
     * <p>本方法**不查注册表**：路由决策必须在会话尚未建立时也能给出，
     * 否则新会话的第一帧音频无处可去。
     *
     * @param sessionId 会话标识
     * @return 处理单元标识
     * @throws SessionRoutingException 映射策略返回 null 时抛出
     */
    public String resolveUnit(String sessionId) {
        if (sessionId == null) {
            throw new SessionRoutingException("sessionId must not be null");
        }
        String unitId = unitResolver.apply(sessionId);
        if (unitId == null) {
            throw new SessionRoutingException("无法为会话 " + sessionId + " 解析处理单元");
        }
        return unitId;
    }

    /**
     * 处理一次心跳超时：回收该会话。
     *
     * <p>心跳超时的会话不能无限期占用处理单元的内存。
     *
     * @param sessionId 会话标识
     */
    public void onHeartbeatTimeout(String sessionId) {
        remove(sessionId);
    }

    /**
     * 查询当前已注册的会话数量。
     *
     * @return 会话数量
     */
    public int size() {
        return sessions.size();
    }
}
