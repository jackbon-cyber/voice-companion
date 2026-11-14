package com.company.bj.voice.cloud.session;

/**
 * 会话上下文。
 *
 * <p>持有一个会话在云端的全部运行时状态。会话状态由 {@link SessionRegistry} 持有，
 * 不落在 Entity 上，也不暴露给 Controller。
 *
 * @param sessionId 会话标识
 * @param unitId 该会话绑定的处理单元标识
 * @param lastHeartbeatMs 最近一次心跳时间戳（毫秒）
 */
public record SessionContext(String sessionId, String unitId, long lastHeartbeatMs) {
}
