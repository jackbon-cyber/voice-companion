package com.company.bj.voice.cloud.session;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.TextWebSocketHandler;

/**
 * 端侧上行通道的 WebSocket 处理器。
 *
 * <p>处理器只做**转发**：消息的业务语义交给 {@link SessionLifecycleService}。
 * 这样协议判定逻辑可以脱离 WebSocket 直接测试。
 *
 * <p>处理器**不因单条坏消息而断开连接**：一条协议不合法的消息不该让设备重连，
 * 重连会丢掉已经积累的会话上下文。
 */
@Component
public class SessionWebSocketHandler extends TextWebSocketHandler {

    /** 日志器。 */
    private static final Logger LOGGER = LoggerFactory.getLogger(SessionWebSocketHandler.class);

    /** 会话生命周期服务。 */
    private final SessionLifecycleService sessionLifecycleService;

    /**
     * 构造处理器。
     *
     * @param sessionLifecycleService 会话生命周期服务
     */
    public SessionWebSocketHandler(SessionLifecycleService sessionLifecycleService) {
        this.sessionLifecycleService = sessionLifecycleService;
    }

    @Override
    protected void handleTextMessage(WebSocketSession session, TextMessage message) {
        try {
            sessionLifecycleService.onUplinkMessage(message.getPayload());
        } catch (RuntimeException error) {
            // 单条消息处理失败不影响连接：记录日志后继续。
            LOGGER.warn("处理上行消息失败，已忽略：{}", error.getMessage());
        }
    }

    @Override
    public void afterConnectionClosed(WebSocketSession session, CloseStatus status) {
        LOGGER.info("上行通道已关闭：{}", status);
    }
}
