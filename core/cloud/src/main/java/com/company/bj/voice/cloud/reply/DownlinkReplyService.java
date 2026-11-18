package com.company.bj.voice.cloud.reply;

import com.company.bj.voice.cloud.downlink.DownlinkPublisher;
import java.io.IOException;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;

/**
 * 下行回复编排服务。
 *
 * <p>把"收到上行意图"翻译成"下发什么回复"。目前云端**没有**意图分类器
 * 与记忆检索（OpenSpec 第 7、9 组未实现），因此这里的回复内容是
 * **明确标注的占位实现**，不是真实的能力。
 *
 * <p>占位实现存在的意义是**让链路闭环可验证**：端侧能收到符合协议的下行消息，
 * 首包延迟能被真实测量；后续替换回复生成逻辑时，协议层与端侧都不用改。
 *
 * <p>替换时保持本类的**输入输出契约**不变即可：
 * 输入是 WebSocket 连接与协议会话标识，输出是下发的协议消息。
 */
@Service
public class DownlinkReplyService {

    /** 日志器。 */
    private static final Logger LOGGER = LoggerFactory.getLogger(DownlinkReplyService.class);

    /** 情感标签：温和陪伴。 */
    private static final String EMOTION_TENDERNESS = "tenderness";

    /** 情感标签：中性。 */
    private static final String EMOTION_NEUTRAL = "neutral";

    /** 下行发布器。 */
    private final DownlinkPublisher downlinkPublisher;

    /**
     * 构造回复编排服务。
     *
     * @param downlinkPublisher 下行发布器
     */
    public DownlinkReplyService(DownlinkPublisher downlinkPublisher) {
        this.downlinkPublisher = downlinkPublisher;
    }

    /**
     * 对一条上行意图给出回复。
     *
     * @param webSocketSession WebSocket 连接
     * @param protocolSessionId 协议会话标识
     * @param intent 意图标识
     * @param handledLocally 该意图是否已在端侧处理
     * @return 实际下发的消息数
     */
    public int replyToIntent(
            WebSocketSession webSocketSession,
            String protocolSessionId,
            String intent,
            boolean handledLocally) {
        String text = buildText(intent, handledLocally);
        String emotion = handledLocally ? EMOTION_NEUTRAL : EMOTION_TENDERNESS;

        LOGGER.info("下发回复：会话={} 意图={} 本地已处理={}", protocolSessionId, intent, handledLocally);
        return sendText(webSocketSession, protocolSessionId, text, emotion);
    }

    /**
     * 下发一条带引用来源的回复。
     *
     * <p>引用来源（{@code citations}）让「这条回复依据了哪条记忆」成为
     * 可机器断言的事实 —— 端到端脚本据此断言跨用户记忆隔离。
     *
     * @param webSocketSession WebSocket 连接
     * @param protocolSessionId 协议会话标识
     * @param intent 意图标识
     * @param handledLocally 该意图是否已在端侧处理
     * @param grounded 记忆支撑的回复
     * @return 实际下发的消息数
     */
    public int replyGrounded(
            WebSocketSession webSocketSession,
            String protocolSessionId,
            String intent,
            boolean handledLocally,
            MemoryGroundedReplyService.GroundedReply grounded) {

        LOGGER.info("下发回复：会话={} 意图={} 本地已处理={} 引用来源={}",
                protocolSessionId, intent, handledLocally, grounded.citations());

        if (webSocketSession == null || !webSocketSession.isOpen()) {
            LOGGER.warn("连接不可用，回复未送达：会话={}", protocolSessionId);
            return 0;
        }
        try {
            String payload = downlinkPublisher.publishText(
                    protocolSessionId, grounded.text(), grounded.emotion(), grounded.citations());
            webSocketSession.sendMessage(new TextMessage(payload));
            return 1;
        } catch (IOException | RuntimeException error) {
            LOGGER.warn("回复下发失败：{}", error.getMessage());
            return 0;
        }
    }

    /**
     * 下发一条文本回复。
     *
     * @param webSocketSession WebSocket 连接
     * @param protocolSessionId 协议会话标识
     * @param text 回复正文
     * @param emotion 情感标签
     * @return 实际下发的消息数
     */
    public int sendText(
            WebSocketSession webSocketSession,
            String protocolSessionId,
            String text,
            String emotion) {
        if (webSocketSession == null || !webSocketSession.isOpen()) {
            LOGGER.warn("连接不可用，回复未送达：会话={}", protocolSessionId);
            return 0;
        }
        try {
            String payload = downlinkPublisher.publishText(protocolSessionId, text, emotion);
            webSocketSession.sendMessage(new TextMessage(payload));
            return 1;
        } catch (IOException | RuntimeException error) {
            LOGGER.warn("回复下发失败：{}", error.getMessage());
            return 0;
        }
    }

    /**
     * 下发一段语音回复。
     *
     * @param webSocketSession WebSocket 连接
     * @param protocolSessionId 协议会话标识
     * @param audioChunks 音频片段的 base64 文本，按播放顺序
     * @return 实际下发的消息数
     */
    public int sendVoice(
            WebSocketSession webSocketSession,
            String protocolSessionId,
            List<String> audioChunks) {
        if (webSocketSession == null || !webSocketSession.isOpen()) {
            LOGGER.warn("连接不可用，语音回复未送达：会话={}", protocolSessionId);
            return 0;
        }
        try {
            List<String> messages = downlinkPublisher.publishVoice(protocolSessionId, audioChunks);
            for (String payload : messages) {
                webSocketSession.sendMessage(new TextMessage(payload));
            }
            return messages.size();
        } catch (IOException | RuntimeException error) {
            LOGGER.warn("语音回复下发失败：{}", error.getMessage());
            return 0;
        }
    }

    /**
     * 构造回复正文。
     *
     * <p>**这是占位实现**：真实回复应由意图三级判定与记忆检索生成
     * （OpenSpec 任务 7.1–7.8、9.1–9.10）。此处只保证消息形态正确、
     * 链路可验证。
     *
     * @param intent 意图标识
     * @param handledLocally 该意图是否已在端侧处理
     * @return 回复正文
     */
    private String buildText(String intent, boolean handledLocally) {
        if (handledLocally) {
            return "好的，已经帮你处理好了。";
        }
        return "我听着呢，你继续说。";
    }
}
