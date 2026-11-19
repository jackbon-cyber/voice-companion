package com.company.bj.voice.cloud.reply;

import com.company.bj.voice.cloud.memory.MemoryRecord;
import com.company.bj.voice.cloud.memory.ScoredMemoryRecord;
import com.company.bj.voice.cloud.memory.companion.MemoryRelevancePolicy;
import com.company.bj.voice.cloud.memory.companion.SessionMemoryOrchestrator;
import java.util.List;
import java.util.Optional;

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
 * <p><b>不编造，也不硬答</b>：没有通过相关性准入的记忆时，
 * 回复如实说明「我这边还没有关于这件事的记录」，
 * 不会凭空生成一条记忆再引用它 ——
 * 那样引用来源就成了装饰，隔离验证也就失去意义。
 *
 * <p><b>为什么需要一个准入层</b>：检索总会返回点什么，哪怕完全不相关。
 * 无条件把第一条当事实陈述，会出现「用户问饮食禁忌，机器人答最爱吃酸菜鱼」
 * 这类**答非所问但听起来有依据**的回复 ——
 * 它比"我不知道"更难被发现，也更容易失去用户信任。
 *
 * <p><b>情感标签</b>与回复同时产生，不额外调用一次模型。
 */
public class MemoryGroundedReplyService {

    /** 候选召回条数上限。 */
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

    /** 相关性准入策略。 */
    private final MemoryRelevancePolicy policy;

    /**
     * 构造回复生成服务。
     *
     * @param orchestrator 记忆编排服务
     * @throws IllegalArgumentException 参数为 null 时抛出
     */
    public MemoryGroundedReplyService(SessionMemoryOrchestrator orchestrator) {
        this(orchestrator, MemoryRelevancePolicy.standard());
    }

    /**
     * 构造回复生成服务。
     *
     * @param orchestrator 记忆编排服务
     * @param policy       相关性准入策略
     * @throws IllegalArgumentException 参数为 null 时抛出
     */
    public MemoryGroundedReplyService(
            SessionMemoryOrchestrator orchestrator, MemoryRelevancePolicy policy) {

        if (orchestrator == null || policy == null) {
            throw new IllegalArgumentException("编排服务与准入策略不能为 null");
        }
        this.orchestrator = orchestrator;
        this.policy = policy;
    }

    /**
     * 为一轮对话生成回复。
     *
     * @param sessionId 会话标识
     * @param text      用户原话
     * @return 回复结果
     */
    public GroundedReply reply(String sessionId, String text) {
        Optional<ScoredMemoryRecord> selected =
                orchestrator.recallForStatement(sessionId, text, RECALL_LIMIT, policy);

        if (selected.isEmpty()) {
            return new GroundedReply(
                    NO_RECALL_TEMPLATE, EMOTION_TENDERNESS, List.of(), List.of());
        }

        // 只把选中的那一条写进文本：多条并列会让回复变成"流水账"，
        // 而陪伴场景的回复应当聚焦。全部记忆标识仍放进引用来源，
        // 便于追溯与端到端断言。
        MemoryRecord primary = selected.get().record();
        String body = String.format(RECALL_TEMPLATE, primary.content());

        return new GroundedReply(
                body,
                EMOTION_TENDERNESS,
                List.of(primary.id()),
                List.of(primary.content()));
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
