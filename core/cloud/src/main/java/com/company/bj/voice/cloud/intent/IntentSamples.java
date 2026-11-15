package com.company.bj.voice.cloud.intent;

import java.util.List;
import java.util.Map;

/**
 * 意图原型示例句库。
 *
 * <p>每条示例句都是<b>真实用户可能说的话</b>，而不是抽象的标签描述。
 * 这点很关键：原型向量是示例句向量的均值，如果示例句写成
 * "音量调节指令"这种标签形态，查询句"把声音调小点"与它的相似度会很低 ——
 * 标签描述与真实表达的分布是错位的。
 *
 * <p><b>示例句数量</b>：每个意图 4 到 6 条。太少则原型覆盖不足，
 * 太多则原型均值被稀释、向语义中心收缩，判别力下降。
 */
public final class IntentSamples {

    /** 工具类不允许实例化。 */
    private IntentSamples() {
        throw new UnsupportedOperationException("utility class");
    }

    /** 调节音量意图。 */
    public static final String SET_VOLUME = "set_volume";

    /** 停止说话意图。 */
    public static final String STOP_SPEAKING = "stop_speaking";

    /** 播放音乐意图。 */
    public static final String PLAY_MUSIC = "play_music";

    /** 查询时间意图。 */
    public static final String CHECK_TIME = "check_time";

    /** 查询天气意图。 */
    public static final String WEATHER_QUERY = "weather_query";

    /** 查询设备状态意图。 */
    public static final String CHECK_DEVICE_STATUS = "check_device_status";

    /** 情绪陪伴意图。 */
    public static final String EMOTIONAL_SUPPORT = "emotional_support";

    /** 闲聊意图。 */
    public static final String CHITCHAT = "chitchat";

    /** 各意图的示例句。 */
    private static final Map<String, List<String>> SAMPLES = Map.of(
        SET_VOLUME, List.of(
            "把音量调到五十",
            "声音大一点",
            "把声音调小一点",
            "音量再高一些",
            "太吵了，声音小点",
            "帮我把声音调大"),
        STOP_SPEAKING, List.of(
            "别说了",
            "停止说话",
            "闭嘴别念了",
            "安静一点",
            "你能别念了吗",
            "先别说了"),
        PLAY_MUSIC, List.of(
            "放首音乐",
            "播放一首歌",
            "来首歌听听",
            "放音乐吧",
            "给我来点音乐",
            "换首歌"),
        CHECK_TIME, List.of(
            "现在几点了",
            "看一下时间",
            "现在什么时间",
            "报时"),
        WEATHER_QUERY, List.of(
            "今天天气怎么样",
            "外面下雨吗",
            "查询天气",
            "明天天气如何",
            "外面冷不冷"),
        CHECK_DEVICE_STATUS, List.of(
            "看看电量",
            "设备状态如何",
            "还能用多久",
            "是不是快没电了",
            "你现在的状态怎么样"),
        EMOTIONAL_SUPPORT, List.of(
            "我今天心情不好",
            "最近很焦虑",
            "我觉得很难过",
            "我有点累",
            "今天很不顺心",
            "我感到孤独"),
        CHITCHAT, List.of(
            "你好呀",
            "在忙什么呢",
            "陪我聊会儿天",
            "今天天气不错",
            "你叫什么名字"));

    /** 各意图的可读名称。 */
    private static final Map<String, String> LABELS = Map.of(
        SET_VOLUME, "调节音量",
        STOP_SPEAKING, "停止说话",
        PLAY_MUSIC, "播放音乐",
        CHECK_TIME, "查询时间",
        WEATHER_QUERY, "查询天气",
        CHECK_DEVICE_STATUS, "查询设备状态",
        EMOTIONAL_SUPPORT, "情绪陪伴",
        CHITCHAT, "闲聊");

    /**
     * 返回示例句库。
     *
     * @return 意图标识到示例句列表的映射
     */
    public static Map<String, List<String>> samples() {
        return SAMPLES;
    }

    /**
     * 返回意图可读名称表。
     *
     * @return 意图标识到名称的映射
     */
    public static Map<String, String> labels() {
        return LABELS;
    }
}
