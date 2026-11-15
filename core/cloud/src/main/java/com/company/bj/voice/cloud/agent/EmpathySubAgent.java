package com.company.bj.voice.cloud.agent;

import com.company.bj.voice.cloud.memory.companion.EmotionClassifier;
import java.util.List;
import java.util.Map;

/**
 * 共情子智能体。
 *
 * <p>负责接住用户的情绪：识别情绪类别，给出对应的陪伴话术。
 *
 * <p><b>共情的优先级低于事实与人设</b>：共情是"软"的，
 * 而安全与事实是"硬"的。当一轮里既有情绪表达又有事实请求时，
 * 应该先答事实，再把情绪带上一句 —— 而不是为了共情而先聊情绪，
 * 用户的实际问题被搁置了。
 */
public class EmpathySubAgent implements SubAgentHandler {

    /** 共情子智能体的优先级。 */
    public static final int PRIORITY = SubAgentArbitrator.PRIORITY_EMOTION;

    /** 情绪陪伴类意图。 */
    public static final String INTENT_EMOTIONAL_SUPPORT = "emotional_support";

    /** 情绪分类器。 */
    private final EmotionClassifier classifier;

    /** 情绪到话术的映射。 */
    private final Map<String, String> phrases;

    /**
     * 构造共情子智能体。
     *
     * @param classifier 情绪分类器
     * @param phrases    情绪到话术的映射
     */
    public EmpathySubAgent(EmotionClassifier classifier, Map<String, String> phrases) {
        this.classifier = classifier;
        this.phrases = Map.copyOf(phrases);
    }

    @Override
    public SubAgentResult handle(SubAgentRequest request) {
        String emotion = classifier.classify(request.text());
        String phrase = phrases.get(emotion);
        if (phrase == null) {
            phrase = phrases.get(EmotionClassifier.NEUTRAL);
        }
        if (phrase == null) {
            return SubAgentResult.of("", request.intent(), emotion);
        }
        return SubAgentResult.of(phrase, request.intent(), emotion);
    }

    @Override
    public List<String> supportedIntents() {
        return List.of(INTENT_EMOTIONAL_SUPPORT);
    }

    @Override
    public int priority() {
        return PRIORITY;
    }
}
