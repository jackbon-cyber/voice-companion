package com.company.bj.voice.cloud.config;

import com.company.bj.voice.cloud.auth.HandshakeAuthInterceptor;
import com.company.bj.voice.cloud.auth.TokenAuthenticator;
import com.company.bj.voice.cloud.downlink.DownlinkPublisher;
import com.company.bj.voice.cloud.protocol.ProtocolValidator;
import com.company.bj.voice.cloud.session.ProcessingUnitDirectory;
import com.company.bj.voice.cloud.session.SessionRegistry;
import com.company.bj.voice.cloud.session.SessionReroutingService;
import java.nio.file.Path;
import java.time.Clock;
import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * 云端基础 Bean 配置。
 *
 * <p>这些 Bean 单独成配置类，是为了避开与 {@link WebSocketConfig} 的循环依赖：
 * WebSocket 配置需要上行处理器，上行处理器需要会话服务，会话服务又需要
 * 这里的协议校验器与会话注册表 —— 把 Bean 定义与 WebSocket 注册拆开，
 * 依赖链才是单向的。
 */
@Configuration
public class CloudBeansConfig {

    /** 协议 schema 所在目录。协议 schema 与 Python 侧共用同一批文件。 */
    private static final Path SCHEMA_DIR = Path.of("..", "protocol", "schema");

    /**
     * 构造协议校验器。
     *
     * @return 协议校验器
     */
    @Bean
    public ProtocolValidator protocolValidator() {
        return new ProtocolValidator(SCHEMA_DIR);
    }

    /**
     * 构造下行发布器。
     *
     * @param protocolValidator 协议校验器
     * @return 下行发布器
     */
    @Bean
    public DownlinkPublisher downlinkPublisher(ProtocolValidator protocolValidator) {
        return new DownlinkPublisher(protocolValidator);
    }

    /**
     * 构造会话注册表。
     *
     * <p>默认按会话标识的哈希取模分片。真实部署应换成一致性哈希 ——
     * 取模分片在处理单元数量变化时会重新映射几乎所有会话。
     *
     * @return 会话注册表
     */
    @Bean
    public SessionRegistry sessionRegistry() {
        return new SessionRegistry(sessionId -> "unit-" + Math.abs(sessionId.hashCode() % 3));
    }

    /**
     * 构造上行通道鉴权器。
     *
     * <p>凭据来自环境变量 {@code VOICE_UPLINK_TOKEN}，仓库内不出现真实值。
     * 未设置时**不启用鉴权** —— 这是开发期的默认形态，让"克隆下来就能跑"成立。
     * 生产部署必须设置，否则上行通道对任何人都开放。
     *
     * @param uplinkToken 期望的凭据；未设置时为空
     * @return 鉴权器
     */
    @Bean
    public TokenAuthenticator tokenAuthenticator(
            @Value("${voice.uplink.token:${VOICE_UPLINK_TOKEN:}}") String uplinkToken) {
        return new TokenAuthenticator(uplinkToken);
    }

    /**
     * 构造握手鉴权拦截器。
     *
     * @param tokenAuthenticator 鉴权器
     * @return 握手鉴权拦截器
     */
    @Bean
    public HandshakeAuthInterceptor handshakeAuthInterceptor(TokenAuthenticator tokenAuthenticator) {
        return new HandshakeAuthInterceptor(tokenAuthenticator);
    }

    /**
     * 构造处理单元可用性来源。
     *
     * <p>第一阶段进程内只有固定的三个逻辑分片，全部视为可用。
     * 真实部署应换成从注册中心或编排系统查询 —— 这正是
     * {@link ProcessingUnitDirectory} 存在的理由：替换实现即可，
     * 重路由逻辑不用改。
     *
     * @return 处理单元可用性来源
     */
    @Bean
    public ProcessingUnitDirectory processingUnitDirectory() {
        return () -> List.of("unit-0", "unit-1", "unit-2");
    }

    /**
     * 构造会话重路由服务。
     *
     * @param sessionRegistry 会话注册表
     * @param unitDirectory 处理单元可用性来源
     * @return 会话重路由服务
     */
    @Bean
    public SessionReroutingService sessionReroutingService(
            SessionRegistry sessionRegistry, ProcessingUnitDirectory unitDirectory) {
        return new SessionReroutingService(sessionRegistry, unitDirectory);
    }

    /**
     * 构造时钟。
     *
     * <p>注入而非直接取系统时间，便于测试里控制时间流逝。
     *
     * @return 时钟
     */
    @Bean
    public Clock clock() {
        return Clock.systemUTC();
    }
}
