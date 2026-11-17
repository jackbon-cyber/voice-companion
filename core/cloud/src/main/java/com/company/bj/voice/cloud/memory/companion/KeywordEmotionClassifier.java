package com.company.bj.voice.cloud.memory.companion;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * 关键词驱动的情绪分类器。
 *
 * <p><b>为什么用关键词表而不是模型</b>（这是本工程的实测裁定）：
 * <ul>
 *   <li>情绪判定需要<b>低延迟</b>：它处在首包预算之内，
 *       多一次模型推理就可能撑破 400 ms 的首包上限；</li>
 *   <li>容错度高：情绪判错的后果只是话术语气略偏，
 *       而事实性判定判错会导致编造，两者的容错度完全不同；</li>
 *   <li>可审计：陪伴机器人要能解释"为什么用了这个语气"，
 *       关键词表能给出确切依据，模型给不出。</li>
 * </ul>
 *
 * <p><b>与端侧 {@code core/edge/dialog/emotion.py} 的关系</b>：
 * 两边用<b>同一套关键词与同一套标签</b>，因此端侧与云端对同一句话的
 * 情绪判定一致。若两端各用各的，同一句话在端侧显示"neutral"、
 * 在云端变成"joy"，用户会看到机器人语气突变。
 *
 * <p><b>取最长命中关键词</b>：长词更具体。
 * "今天不开心" 命中 "不开心"（sadness），
 * "今天不开心，但刚才那个笑话真的很好笑" 同时命中 "笑话"（joy）与 "不开心"，
 * 取最长词会落到 sadness —— 这里存在固有歧义，
 * 但"先取更长词"比"先取字典序"更可预期。
 */
public class KeywordEmotionClassifier implements EmotionClassifier {

    /** 中性标签。与协议 {@code text-reply.schema.json} 的 emotion 枚举一致。 */
    public static final String NEUTRAL = "neutral";

    /** 喜悦。 */
    public static final String JOY = "joy";

    /** 悲伤。 */
    public static final String SADNESS = "sadness";

    /** 愤怒。 */
    public static final String ANGER = "anger";

    /** 恐惧。 */
    public static final String FEAR = "fear";

    /** 惊讶。 */
    public static final String SURPRISE = "surprise";

    /** 温柔。 */
    public static final String TENDERNESS = "tenderness";

    /** 鼓励。 */
    public static final String ENCOURAGEMENT = "encouragement";

    /** 全部情感标签。顺序固定，便于报告与断言。 */
    public static final List<String> EMOTION_TAGS = List.of(
        NEUTRAL, JOY, SADNESS, ANGER, FEAR, SURPRISE, TENDERNESS, ENCOURAGEMENT);

    /**
     * 情感关键词表。键为情感标签，值为候选关键词。
     *
     * <p>只用<b>两字及以上</b>的高区分度词：像"喜""怒"这类单字会命中
     * "喜欢""遇见"等无关表达，把情绪判反比判成 neutral 更伤体验。
     */
    private static final Map<String, List<String>> EMOTION_KEYWORDS = buildKeywords();

    /**
     * 构建关键词表。
     *
     * @return 标签到关键词列表的映射
     */
    private static Map<String, List<String>> buildKeywords() {
        Map<String, List<String>> keywords = new LinkedHashMap<>();
        keywords.put(JOY, List.of(
            "开心", "高兴", "太好了", "真棒", "真好", "哈哈", "顺利", "好消息", "升职", "成功了"));
        keywords.put(SADNESS, List.of(
            "难过", "伤心", "想哭", "失落", "委屈", "不开心", "很低落", "沮丧", "白忙了"));
        keywords.put(ANGER, List.of(
            "生气", "气死", "烦死", "烦人", "讨厌", "恼火", "火大", "忍不了"));
        keywords.put(FEAR, List.of(
            "害怕", "担心", "紧张", "恐惧", "不安", "焦虑", "好怕"));
        keywords.put(SURPRISE, List.of(
            "没想到", "居然", "竟然", "突然", "惊讶", "天啊", "不会吧"));
        keywords.put(TENDERNESS, List.of(
            "喜欢你", "想你了", "抱抱", "陪我", "爱你", "好想你", "想见你"));
        keywords.put(ENCOURAGEMENT, List.of(
            "加油", "坚持", "努力", "别放弃", "你可以的", "我相信你", "再试试"));
        return Map.copyOf(keywords);
    }

    @Override
    public String classify(String text) {
        if (text == null || text.isBlank()) {
            return NEUTRAL;
        }
        String normalized = text.toLowerCase(Locale.ROOT);

        String bestTag = NEUTRAL;
        int bestLength = 0;
        for (Map.Entry<String, List<String>> entry : EMOTION_KEYWORDS.entrySet()) {
            for (String keyword : entry.getValue()) {
                if (!normalized.contains(keyword)) {
                    continue;
                }
                if (keyword.length() > bestLength) {
                    bestTag = entry.getKey();
                    bestLength = keyword.length();
                }
            }
        }
        return bestTag;
    }
}
