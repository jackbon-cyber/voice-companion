package com.company.bj.voice.cloud.session;

import com.company.bj.voice.cloud.downlink.DownlinkPublisher;
import com.company.bj.voice.cloud.reply.DownlinkReplyService;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.TextWebSocketHandler;

/**
 * 端云双向通道的 WebSocket 处理器。
 *
 * <p>上行只做**转发**：消息的业务语义交给 {@link SessionLifecycleService}。
 * 这样协议判定逻辑可以脱离 WebSocket 直接测试。
 *
 * <p>下行把 {@link DownlinkReplyService} 编排好的消息写回连接。
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

    /** 下行发布器。 */
    private final DownlinkPublisher downlinkPublisher;

    /** 下行回复编排服务。 */
    private final DownlinkReplyService downlinkReplyService;

    /**
     * 构造处理器。
     *
     * @param sessionLifecycleService 会话生命周期服务
     * @param downlinkPublisher 下行发布器
     * @param downlinkReplyService 下行回复编排服务
     */
    public SessionWebSocketHandler(
            SessionLifecycleService sessionLifecycleService,
            DownlinkPublisher downlinkPublisher,
            DownlinkReplyService downlinkReplyService) {
        this.sessionLifecycleService = sessionLifecycleService;
        this.downlinkPublisher = downlinkPublisher;
        this.downlinkReplyService = downlinkReplyService;
    }

    @Override
    protected void handleTextMessage(WebSocketSession session, TextMessage message) {
        try {
            sessionLifecycleService.onUplinkMessage(message.getPayload());
        } catch (RuntimeException error) {
            // 单条消息处理失败不影响连接：记录日志后继续。
            LOGGER.warn("处理上行消息失败，已忽略：{}", error.getMessage());
            return;
        }

        // 上行意图触发的回复。放在 try 之外是为了让回复失败不影响上行处理，
        // 但也不影响后续消息的继续处理。
        try {
            replyIfIntent(session, message.getPayload());
        } catch (RuntimeException error) {
            LOGGER.warn("下行回复失败，已忽略：{}", error.getMessage());
        }
    }

    /**
     * 若上行消息是意图报告，则下发一条回复。
     *
     * @param session WebSocket 会话
     * @param payload 上行消息 JSON 文本
     */
    private void replyIfIntent(WebSocketSession session, String payload) {
        if (!payload.contains("\"intent\"")) {
            return;
        }
        String protocolSessionId = extractSessionId(payload);
        if (protocolSessionId == null) {
            return;
        }
        String intent = extractField(payload, "intent");
        boolean handledLocally = payload.contains("\"handledLocally\":true");
        downlinkReplyService.replyToIntent(session, protocolSessionId, intent, handledLocally);
    }

    /**
     * 下发一段语音回复。
     *
     * @param session WebSocket 会话
     * @param protocolSessionId 协议会话标识（消息体里的 sessionId）
     * @param audioChunks 音频片段的 base64 文本，按播放顺序
     * @return 成功下发的消息数
     */
    public int sendVoice(
            WebSocketSession session, String protocolSessionId, List<String> audioChunks) {
        return downlinkReplyService.sendVoice(session, protocolSessionId, audioChunks);
    }

    /**
     * 下发一条文本回复。
     *
     * @param session WebSocket 会话
     * @param protocolSessionId 协议会话标识（消息体里的 sessionId）
     * @param text 回复正文
     * @param emotion 情感标签
     * @return 是否下发成功
     */
    public boolean sendText(
            WebSocketSession session, String protocolSessionId, String text, String emotion) {
        return downlinkReplyService.sendText(session, protocolSessionId, text, emotion) > 0;
    }

    private String extractSessionId(String payload) {
        return extractField(payload, "sessionId");
    }

    /**
     * 从 JSON 文本里取一个字符串字段。
     *
     * <p>这里刻意用**轻量字符串解析**而不是完整的 JSON 解析器：
     * 上行消息的字段名与顺序是协议固定的，正则足够；
     * 而这条路径在每条消息上都会走，多解析一次 JSON 是无谓的开销。
     * 完整的协议校验由 {@code ProtocolValidator} 负责，不在这里重复。
     *
     * @param payload JSON 文本
     * @param fieldName 字段名
     * @return 字段值；未找到时为 null
     */
    private String extractField(String payload, String fieldName) {
        java.util.regex.Matcher matcher =
                java.util.regex.Pattern.compile("\"" + fieldName + "\"\\s*:\\s*\"([^\"]*)\"").matcher(payload);
        if (!matcher.find()) {
            return null;
        }
        return matcher.group(1);
    }

    @Override
    public void afterConnectionClosed(WebSocketSession session, CloseStatus status) {
        LOGGER.info("上行通道已关闭：{}", status);
    }
}
