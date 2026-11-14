package com.company.bj.voice.cloud.downlink;

import com.company.bj.voice.cloud.protocol.ProtocolValidator;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * 下行消息发布器。
 *
 * <p>负责把云端生成的回复编排成**协议规定的下行消息序列**：
 * 语音片段带首包/末包标记、序号连续；文本回复带情感标签与可选引用来源。
 *
 * <p>序号按**会话**维护：同一会话的下行序号连续递增，
 * 端侧才能判断是否漏收。序号存内存里，多实例部署时需要外置
 * （与 {@code SessionRegistry} 的进程内状态是同一类限制）。
 *
 * <p>发布前**一律做协议校验**。下行消息发出去端侧就无从申诉 ——
 * 一条不合协议的消息会让端侧的解析直接失败，比慢一点严重得多。
 */
public class DownlinkPublisher {

    /** 协议 schema 名。 */
    private static final String VOICE_CHUNK_SCHEMA = "voice-chunk";

    /** 文本回复 schema 名。 */
    private static final String TEXT_REPLY_SCHEMA = "text-reply";

    /** 协议允许的情感标签集合。与 text-reply schema 的 enum 一致。 */
    private static final Set<String> ALLOWED_EMOTIONS = Set.of(
            "neutral", "joy", "sadness", "anger", "fear", "surprise", "tenderness", "encouragement");

    /** 协议校验器。 */
    private final ProtocolValidator protocolValidator;

    /** JSON 序列化器。 */
    private final ObjectMapper objectMapper = new ObjectMapper();

    /** 会话标识到下一个下行序号的映射。 */
    private final ConcurrentHashMap<String, AtomicInteger> sequenceBySession = new ConcurrentHashMap<>();

    /**
     * 构造下行发布器。
     *
     * @param protocolValidator 协议校验器
     */
    public DownlinkPublisher(ProtocolValidator protocolValidator) {
        this.protocolValidator = protocolValidator;
    }

    /**
     * 发布一段语音回复。
     *
     * @param sessionId 会话标识
     * @param audioChunks 音频片段的 base64 文本，按播放顺序
     * @return 下发消息 JSON 文本序列
     * @throws IllegalArgumentException 会话标识为空、片段为空或某个片段内容为空时抛出
     */
    public List<String> publishVoice(String sessionId, List<String> audioChunks) {
        requireSessionId(sessionId);
        if (audioChunks == null || audioChunks.isEmpty()) {
            throw new IllegalArgumentException("voice chunk list must not be empty");
        }

        AtomicInteger sequence = nextSequence(sessionId);
        List<String> messages = new ArrayList<>(audioChunks.size());
        int lastIndex = audioChunks.size() - 1;

        for (int index = 0; index < audioChunks.size(); index++) {
            String payload = audioChunks.get(index);
            if (payload == null || payload.isBlank()) {
                throw new IllegalArgumentException("voice chunk at index " + index + " must not be blank");
            }

            ObjectNode node = objectMapper.createObjectNode();
            node.put("sessionId", sessionId);
            node.put("sequence", sequence.getAndIncrement());
            node.put("payloadBase64", payload);
            node.put("isFirst", index == 0);
            node.put("isLast", index == lastIndex);

            messages.add(serialize(node));
        }
        return messages;
    }

    /**
     * 发布一条文本回复。
     *
     * @param sessionId 会话标识
     * @param text 回复正文
     * @param emotion 情感标签
     * @return 下发消息 JSON 文本
     * @throws IllegalArgumentException 参数不合法时抛出
     */
    public String publishText(String sessionId, String text, String emotion) {
        return publishText(sessionId, text, emotion, List.of());
    }

    /**
     * 发布一条文本回复。
     *
     * @param sessionId 会话标识
     * @param text 回复正文
     * @param emotion 情感标签
     * @param citations 引用的记忆或知识片段标识，可为空
     * @return 下发消息 JSON 文本
     * @throws IllegalArgumentException 参数不合法时抛出
     */
    public String publishText(String sessionId, String text, String emotion, List<String> citations) {
        requireSessionId(sessionId);
        if (text == null || text.isBlank()) {
            throw new IllegalArgumentException("text must not be blank");
        }
        if (!ALLOWED_EMOTIONS.contains(emotion)) {
            throw new IllegalArgumentException("emotion must be one of " + ALLOWED_EMOTIONS);
        }

        ObjectNode node = objectMapper.createObjectNode();
        node.put("sessionId", sessionId);
        node.put("text", text);
        node.put("emotion", emotion);

        if (citations != null && !citations.isEmpty()) {
            ArrayNode citationArray = node.putArray("citations");
            citations.forEach(citationArray::add);
        }

        return serialize(node);
    }

    /**
     * 校验一条语音片段消息。
     *
     * @param payload 消息 JSON 文本
     * @return 错误列表，空列表表示通过
     */
    public List<String> validateChunk(String payload) {
        return protocolValidator.validate(VOICE_CHUNK_SCHEMA, payload);
    }

    /**
     * 校验一条文本回复消息。
     *
     * @param payload 消息 JSON 文本
     * @return 错误列表，空列表表示通过
     */
    public List<String> validateText(String payload) {
        return protocolValidator.validate(TEXT_REPLY_SCHEMA, payload);
    }

    private AtomicInteger nextSequence(String sessionId) {
        return sequenceBySession.computeIfAbsent(sessionId, key -> new AtomicInteger(0));
    }

    private void requireSessionId(String sessionId) {
        if (sessionId == null || sessionId.isBlank()) {
            throw new IllegalArgumentException("sessionId must not be blank");
        }
    }

    private String serialize(ObjectNode node) {
        try {
            return objectMapper.writeValueAsString(node);
        } catch (JsonProcessingException error) {
            throw new IllegalStateException("序列化下行消息失败", error);
        }
    }
}
