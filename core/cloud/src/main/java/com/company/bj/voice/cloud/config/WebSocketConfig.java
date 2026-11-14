package com.company.bj.voice.cloud.config;

import com.company.bj.voice.cloud.session.SessionWebSocketHandler;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.socket.config.annotation.EnableWebSocket;
import org.springframework.web.socket.config.annotation.WebSocketConfigurer;
import org.springframework.web.socket.config.annotation.WebSocketHandlerRegistry;

/**
 * 云端 WebSocket 配置。
 */
@Configuration
@EnableWebSocket
public class WebSocketConfig implements WebSocketConfigurer {

    /** 端侧上行通道路径。 */
    private static final String UPLINK_PATH = "/voice/uplink";

    /** 上行通道处理器。 */
    private final SessionWebSocketHandler sessionWebSocketHandler;

    /**
     * 构造配置。
     *
     * @param sessionWebSocketHandler 上行通道处理器
     */
    public WebSocketConfig(SessionWebSocketHandler sessionWebSocketHandler) {
        this.sessionWebSocketHandler = sessionWebSocketHandler;
    }

    @Override
    public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
        registry.addHandler(sessionWebSocketHandler, UPLINK_PATH)
                .setAllowedOriginPatterns("*");
    }
}
