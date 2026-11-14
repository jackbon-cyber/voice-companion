package com.company.bj.voice.cloud.config;

import com.company.bj.voice.cloud.protocol.ProtocolValidator;
import com.company.bj.voice.cloud.session.SessionRegistry;
import java.nio.file.Path;
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
}
