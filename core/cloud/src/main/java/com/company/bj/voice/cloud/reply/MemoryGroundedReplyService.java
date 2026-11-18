package com.company.bj.voice.cloud.reply;

import com.company.bj.voice.cloud.memory.MemoryRecord;
import com.company.bj.voice.cloud.memory.companion.SessionMemoryOrchestrator;
import java.util.List;

/**
 * 记忆支撑的回复生成服务。
 *
 * <p>生成一条**带引用来源**的回复：召回当前用户作用域下的记忆，
 * 把命中的记忆内容织进回复文本，并把记忆标识放进协议的 {@code citations} 字段。
 *
 * <p><b>为什么回复必须带引用来源</b>：没有引用来源时，
 * 「跨用户记忆隔离」只能靠人读回复文本去判断 —— 那既不可靠也不可复现。
 * 引用来源让「这条回复依据了哪条记忆」成为**可机器断言**的事实：
 * 端到端脚本可以直接断言「用户 B 的回复没有引用用户 A 的记忆标识」。
 *
 * <p><b>不编造</b>：召回不到记忆时，回复如实说明「我这边没有相关记录」，
 * 不会凭空生成一条记忆再引用它 ——
 * 那样引用来源就成了装饰，隔离验证也就失去意义。
 *
 * <p><b>情感标签</b>与回复同时产生，不额外调用一次模型。
 */
public class MemoryGroundedReplyService {

    /** 召回条数上限。 */
    public static final int RECALL_LIMIT = 5;

    /** 情感标签：温和陪伴。 */
    public static final String EMOTION_TENDERNESS = "tenderness";

    /** 情感标签：中性。 */
    public static final String EMOTION_NEUTRAL = "neutral";

    /** 记起时的回复模板。 */
    private static final String RECALL_TEMPLATE = "我记得，%s";

    /** 记不起时的回复模板。 */
    private static final String NO_RECALL_TEMPLATE = "我这边还没有关于这件事的记录，你说得再具体一点我就能记下了。";

    /** 记忆编排服务。 */
    private final SessionMemoryOrchestrator orchestrator;

    /**
     * 构造回复生成服务。
     *
     * @param orchestrator 记忆编排服务
     * @throws IllegalArgumentException 参数为 null 时抛出
     */
    public MemoryGroundedReplyService(SessionMemoryOrchestrator orchestrator) {
        if (orchestrator == null) {
            throw new IllegalArgumentException("orchestrator must not be null");
        }
        this.orchestrator = orchestrator;
    }

    /**
     * 为一轮对话生成回复。
     *
     * @param sessionId 会话标识
     * @param text      用户原话
     * @return 回复结果
     */
    public GroundedReply reply(String sessionId, String text) {
        List<MemoryRecord> recalled =
                orchestrator.recall(sessionId, text, RECALL_LIMIT);

        if (recalled.isEmpty()) {
            return new GroundedReply(
                    NO_RECALL_TEMPLATE, EMOTION_TENDERNESS, List.of(), List.of());
        }

        // 只把最靠前的一条写进文本：多条并列会让回复变成"流水账"，
        // 而陪伴场景的回复应当聚焦。全部记忆标识仍放进引用来源，
        // 便于追溯与端到端断言。
        String primary = recalled.get(0).content();
        String body = String.format(RECALL_TEMPLATE, primary);

        return new GroundedReply(
                body,
                EMOTION_TENDERNESS,
                recalled.stream().map(MemoryRecord::id).toList(),
                recalled.stream().map(MemoryRecord::content).toList());
    }

    /**
     * 一条带引用来源的回复。
     *
     * @param text       回复正文
     * @param emotion    情感标签
     * @param citations  引用的记忆标识
     * @param sources    引用的记忆内容
     */
    public record GroundedReply(
        String text, String emotion, List<String> citations, List<String> sources) {

        /**
         * 判断回复是否依据了记忆。
         *
         * @return 有引用来源返回 {@code true}
         */
        public boolean grounded() {
            return !citations.isEmpty();
        }
    }
}
