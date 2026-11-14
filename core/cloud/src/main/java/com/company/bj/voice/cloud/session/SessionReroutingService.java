package com.company.bj.voice.cloud.session;

import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

/**
 * 处理单元失效后的会话重路由服务。
 *
 * <p><b>为什么重路由要保上下文</b>：会话上下文（对话历史、已装配的记忆）
 * 都在处理单元的内存里。会话漂到别的单元，上下文就接不上了，
 * 用户会感到"机器人失忆" —— 这恰恰是陪伴场景最不能接受的失败形态。
 *
 * <p><b>为什么重路由不等于重新开始</b>：重路由只换**执行位置**，
 * 不重置对话状态。会话标识与最近心跳时间都保留。
 *
 * <p><b>为什么没有可用单元时不重路由</b>：此时把会话挪到任何地方都是错的 ——
 * 没有可用单元意味着整个集群都不可用，把会话标成"已迁移"只是把故障往后推。
 * 正确做法是**保留原绑定**，等单元恢复后由恢复流程接手。
 * 会话最终会因心跳超时被回收，不会无限泄漏。
 *
 * <p>本类属于 Service 层，只依赖 {@link SessionRegistry} 与
 * {@link ProcessingUnitDirectory}，不依赖任何 Repository。
 */
@Service
public class SessionReroutingService {

    /** 日志器。 */
    private static final Logger LOGGER = LoggerFactory.getLogger(SessionReroutingService.class);

    /** 会话注册表。 */
    private final SessionRegistry sessionRegistry;

    /** 处理单元可用性来源。 */
    private final ProcessingUnitDirectory unitDirectory;

    /**
     * 构造重路由服务。
     *
     * @param sessionRegistry 会话注册表
     * @param unitDirectory 处理单元可用性来源
     */
    public SessionReroutingService(
            SessionRegistry sessionRegistry, ProcessingUnitDirectory unitDirectory) {
        this.sessionRegistry = sessionRegistry;
        this.unitDirectory = unitDirectory;
    }

    /**
     * 把某个处理单元上的全部会话重路由到其他可用单元。
     *
     * @param failedUnitId 失效的处理单元标识
     * @return 重路由的会话数
     */
    public int rerouteSessionsOf(String failedUnitId) {
        if (failedUnitId == null) {
            return 0;
        }
        List<SessionContext> affected = sessionRegistry.findByUnit(failedUnitId);
        if (affected.isEmpty()) {
            return 0;
        }

        int rerouted = 0;
        for (SessionContext context : affected) {
            if (rerouteSession(context.sessionId(), failedUnitId)) {
                rerouted++;
            }
        }
        LOGGER.info("处理单元 {} 失效，重路由 {} 个会话", failedUnitId, rerouted);
        return rerouted;
    }

    /**
     * 把单个会话重路由到其他可用单元。
     *
     * @param sessionId 会话标识
     * @param failedUnitId 失效的处理单元标识；用于避免选回同一个单元
     * @return 是否重路由成功
     */
    public boolean rerouteSession(String sessionId, String failedUnitId) {
        String targetUnit = selectTargetUnit(failedUnitId);
        if (targetUnit == null) {
            // 没有可用单元：保留原绑定，等单元恢复或会话因心跳超时被回收。
            LOGGER.warn("处理单元 {} 失效，但当前无可用单元，会话 {} 保留原绑定", failedUnitId, sessionId);
            return false;
        }

        SessionContext rebound = sessionRegistry.rebind(sessionId, targetUnit);
        LOGGER.info("会话已重路由：{} → 处理单元 {}", sessionId, rebound.unitId());
        return true;
    }

    /**
     * 选出一个目标处理单元。
     *
     * <p>排除失效单元本身 —— 把会话挪回刚挂掉的单元没有任何意义。
     *
     * @param failedUnitId 失效的处理单元标识
     * @return 目标单元标识；没有可用单元时返回 null
     */
    private String selectTargetUnit(String failedUnitId) {
        for (String unitId : unitDirectory.availableUnits()) {
            if (!unitId.equals(failedUnitId)) {
                return unitId;
            }
        }
        return null;
    }
}
