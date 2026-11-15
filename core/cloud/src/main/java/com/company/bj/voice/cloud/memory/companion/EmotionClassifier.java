package com.company.bj.voice.cloud.memory.companion;

/**
 * 情绪分类器端口。
 *
 * <p>抽象成接口是为了让共情子智能体不绑定具体的情绪识别实现：
 * 默认用关键词表（零依赖、零延迟），将来接入模型时只需换实现。
 */
@FunctionalInterface
public interface EmotionClassifier {

    /** 中性情绪标签。 */
    String NEUTRAL = "neutral";

    /**
     * 判定一段文本的情绪。
     *
     * @param text 用户文本
     * @return 情绪标签
     */
    String classify(String text);
}
