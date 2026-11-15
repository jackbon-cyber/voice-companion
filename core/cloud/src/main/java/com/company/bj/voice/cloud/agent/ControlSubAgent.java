package com.company.bj.voice.cloud.agent;

import java.util.List;

/**
 * 主控子智能体。
 *
 * <p>负责"没匹配到专门处理器"时的兜底应答：闲聊、开放话题。
 *
 * <p><b>主控的输出是陪伴语，不是功能语</b>：它不需要执行任何操作，
 * 只需要接住用户的话并给出回应。功能性的请求由各自的专门处理器接管。
 */
public class ControlSubAgent implements SubAgentHandler {

    /** 主控的优先级。 */
    public static final int PRIORITY = SubAgentArbitrator.PRIORITY_EMOTION;

    /** 闲聊类意图。 */
    public static final String INTENT_CHITCHAT = "chitchat";

    /** 未识别的兜底意图。 */
    public static final String INTENT_FALLBACK = "fallback";

    /** 话术表。 */
    private final java.util.Map<String, String> phrases;

    /**
     * 构造主控子智能体。
     *
     * @param phrases 意图到话术的映射
     */
    public ControlSubAgent(java.util.Map<String, String> phrases) {
        this.phrases = java.util.Map.copyOf(phrases);
    }

    @Override
    public SubAgentResult handle(SubAgentRequest request) {
        String phrase = phrases.get(request.intent());
        if (phrase == null) {
            phrase = phrases.get(INTENT_FALLBACK);
        }
        if (phrase == null) {
            return SubAgentResult.of("", request.intent(), "neutral");
        }
        return SubAgentResult.of(phrase, request.intent(), "neutral");
    }

    @Override
    public List<String> supportedIntents() {
        return List.of(INTENT_CHITCHAT, INTENT_FALLBACK);
    }

    @Override
    public int priority() {
        return PRIORITY;
    }
}
