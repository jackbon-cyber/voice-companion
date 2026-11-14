package com.company.bj.voice.cloud.session;

import java.time.Clock;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * 会话心跳扫描器。
 *
 * <p>定时把心跳超时的会话回收掉，并回收失效单元上的会话。
 *
 * <p><b>为什么需要定时扫描</b>：端侧可能直接断网消失，既发不出
 * {@code end} 消息，也发不出心跳。没有扫描器的话，这些会话会永远
 * 占住处理单元的内存 —— 设备装机量上去后就是一个内存泄漏。
 *
 * <p><b>为什么用定时任务而不是在消息处理时顺带检查</b>：没有新消息进来时
 * 就没人触发检查了 —— 而"设备断网后不再发消息"恰恰是最需要回收的场景。
 * 触发时机与被检查对象必须是解耦的。
 *
 * <p><b>为什么扫描间隔要独立于超时阈值</b>：两者是不同性质的量 ——
 * 超时阈值是**业务容忍度**（多久算失联），扫描间隔是**运维成本**
 * （多久检查一次）。前者由用户体验决定，后者由系统规模决定。
 * 第一阶段的默认值偏保守，接入真实设备后应按规模调整。
 */
@Component
public class SessionHeartbeatScanner {

    /** 日志器。 */
    private static final Logger LOGGER = LoggerFactory.getLogger(SessionHeartbeatScanner.class);

    /** 会话注册表。 */
    private final SessionRegistry sessionRegistry;

    /** 重路由服务。 */
    private final SessionReroutingService reroutingService;

    /** 时钟。注入而非直接取系统时间，便于测试。 */
    private final Clock clock;

    /** 心跳超时阈值（毫秒）。 */
    private final long heartbeatTimeoutMs;

    /**
     * 构造扫描器。
     *
     * @param sessionRegistry 会话注册表
     * @param reroutingService 重路由服务
     * @param clock 时钟
     * @param heartbeatTimeoutMs 心跳超时阈值（毫秒）
     */
    public SessionHeartbeatScanner(
            SessionRegistry sessionRegistry,
            SessionReroutingService reroutingService,
            Clock clock,
            @Value("${voice.session.heartbeat-timeout-ms:90000}") long heartbeatTimeoutMs) {
        this.sessionRegistry = sessionRegistry;
        this.reroutingService = reroutingService;
        this.clock = clock;
        this.heartbeatTimeoutMs = heartbeatTimeoutMs;
    }

    /**
     * 扫描并回收心跳超时的会话。
     *
     * @return 回收的会话数
     */
    @Scheduled(fixedDelayString = "${voice.session.scan-interval-ms:30000}")
    public int scanExpiredSessions() {
        long now = clock.millis();
        List<SessionContext> expired = sessionRegistry.findExpired(now, heartbeatTimeoutMs);
        for (SessionContext context : expired) {
            sessionRegistry.remove(context.sessionId());
            LOGGER.info(
                    "会话心跳超时，已回收：{}（最后心跳距今 {}ms，阈值 {}ms）",
                    context.sessionId(),
                    now - context.lastHeartbeatMs(),
                    heartbeatTimeoutMs);
        }
        return expired.size();
    }

    /**
     * 处理某个处理单元失效：把其上的会话重路由走。
     *
     * <p>本方法目前由运维流程或单元健康检查回调触发，
     * 尚未接到具体的健康检查来源 —— 接入注册中心后由其回调驱动。
     *
     * @param failedUnitId 失效的处理单元标识
     * @return 重路由的会话数
     */
    public int onProcessingUnitFailed(String failedUnitId) {
        return reroutingService.rerouteSessionsOf(failedUnitId);
    }
}
