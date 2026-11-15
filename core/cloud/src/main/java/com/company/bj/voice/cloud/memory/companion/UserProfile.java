package com.company.bj.voice.cloud.memory.companion;

import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 用户画像。
 *
 * <p>五个维度各司其职：
 * <ul>
 *   <li><b>称呼</b>（{@link #preferredAddress}）—— 机器人怎么称呼用户；</li>
 *   <li><b>语气</b>（{@link #tone}）—— 机器人的语气基调；</li>
 *   <li><b>话题权重</b>（{@link #topicWeights}）—— 用户常聊什么；</li>
 *   <li><b>忌讳</b>（{@link #taboos}）—— <b>绝不主动提及</b>的话题；</li>
 *   <li><b>情绪基线</b>（{@link #emotionalBaseline}）—— 用户的常态情绪倾向。</li>
 * </ul>
 *
 * <p><b>忌讳的语义是"拦截"而非"回避"</b>：话题出现在忌讳里时，
 * 该话题<b>不能进入回复</b>，也不能成为主动引导的话题。
 * 仅仅"不说"是不够的 —— 用户问起时也要挡回去。
 */
public record UserProfile(
    String preferredAddress,
    Tone tone,
    Map<String, Double> topicWeights,
    Set<String> taboos,
    EmotionalBaseline emotionalBaseline) {

    /** 语气基调。 */
    public enum Tone {

        /** 温柔耐心，语速偏慢。 */
        WARM,

        /** 活泼开朗。 */
        LIVELY,

        /** 沉稳可靠。 */
        STEADY,

        /** 幽默轻松。 */
        PLAYFUL,

        /** 平实直接。 */
        PLAIN
    }

    /** 情绪基线。 */
    public enum EmotionalBaseline {

        /** 偏积极。 */
        POSITIVE,

        /** 偏消极。 */
        NEGATIVE,

        /** 中性。 */
        NEUTRAL
    }

    /** 主题权重的最低值。低于此值视为不关注。 */
    public static final double MIN_TOPIC_WEIGHT = 0.1;

    /**
     * 判断某个话题是否属于忌讳。
     *
     * <p>委托 {@link TabooMatcher} 做判定 —— 它不仅做字面子串匹配，
     * 还识别已知变体（"前任"能拦住"我前男友"）。
     *
     * @param topic 话题文本
     * @return 属于忌讳返回 {@code true}
     */
    public boolean isTaboo(String topic) {
        if (topic == null || topic.isBlank() || taboos.isEmpty()) {
            return false;
        }
        return new TabooMatcher().matchedTaboos(topic, taboos).size() > 0;
    }

    /**
     * 取得某话题的关注度。
     *
     * @param topic 话题文本
     * @return 关注度；未记录时返回 0
     */
    public double topicWeight(String topic) {
        if (topic == null || topic.isBlank() || topicWeights.isEmpty()) {
            return 0.0;
        }
        for (Map.Entry<String, Double> entry : topicWeights.entrySet()) {
            if (topic.contains(entry.getKey())) {
                return entry.getValue();
            }
        }
        return 0.0;
    }

    /**
     * 取得关注度最高的话题。
     *
     * @return 话题文本；无任何记录时返回空字符串
     */
    public String dominantTopic() {
        String best = "";
        double bestWeight = 0.0;
        for (Map.Entry<String, Double> entry : topicWeights.entrySet()) {
            if (entry.getValue() > bestWeight) {
                bestWeight = entry.getValue();
                best = entry.getKey();
            }
        }
        return best;
    }

    /**
     * 构造一份空画像。
     *
     * @return 空画像
     */
    public static UserProfile empty() {
        return new UserProfile("", Tone.WARM, Map.of(), Set.of(), EmotionalBaseline.NEUTRAL);
    }

    /**
     * 构造一份画像。
     *
     * @param preferredAddress   称呼
     * @param tone               语气
     * @param topicWeights       话题权重
     * @param taboos             忌讳话题
     * @param emotionalBaseline  情绪基线
     * @return 画像
     */
    public static UserProfile of(
        String preferredAddress,
        Tone tone,
        Map<String, Double> topicWeights,
        Set<String> taboos,
        EmotionalBaseline emotionalBaseline) {
        return new UserProfile(
            preferredAddress == null ? "" : preferredAddress,
            tone == null ? Tone.WARM : tone,
            Map.copyOf(topicWeights == null ? Map.of() : topicWeights),
            Set.copyOf(taboos == null ? Set.of() : taboos),
            emotionalBaseline == null ? EmotionalBaseline.NEUTRAL : emotionalBaseline);
    }

    /**
     * 判断画像是否有任何可用的信息。
     *
     * @return 画像为空返回 {@code true}
     */
    public boolean blank() {
        return preferredAddress.isBlank()
            && topicWeights.isEmpty()
            && taboos.isEmpty()
            && tone == Tone.WARM
            && emotionalBaseline == EmotionalBaseline.NEUTRAL;
    }
}
