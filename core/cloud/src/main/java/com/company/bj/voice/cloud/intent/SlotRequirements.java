package com.company.bj.voice.cloud.intent;

import java.util.List;
import java.util.Map;

/**
 * 各意图的必填槽位定义。
 *
 * <p><b>为什么槽位要求要集中在一处</b>：槽位要求散落在各个处理类里时，
 * "哪些意图需要追问"这个问题就要翻遍代码才能回答。
 * 集中在一处后，新增意图时只要在这里登记一行，
 * 澄清流程自动知道该问什么。
 *
 * <p><b>为什么大部分意图没有必填槽位</b>：陪伴场景里追问太多会破坏对话节奏 ——
 * 用户说"我有点累"，机器人回"你累到什么程度呢"是机械的。
 * 只有<b>缺了参数就完全无法执行</b>的意图才设必填槽位。
 */
public final class SlotRequirements {

    /** 工具类不允许实例化。 */
    private SlotRequirements() {
        throw new UnsupportedOperationException("utility class");
    }

    /** 音量的必填槽位。 */
    public static final String SLOT_VOLUME_LEVEL = "volume_level";

    /** 意图标识到必填槽位的映射。 */
    private static final Map<String, List<String>> REQUIRED = Map.of(
        IntentSamples.SET_VOLUME, List.of(SLOT_VOLUME_LEVEL));

    /**
     * 返回某意图的必填槽位。
     *
     * @param intent 意图标识
     * @return 必填槽位列表；无必填槽位时返回空列表
     */
    public static List<String> requiredSlots(String intent) {
        return REQUIRED.getOrDefault(intent, List.of());
    }

    /**
     * 判断某意图是否有必填槽位。
     *
     * @param intent 意图标识
     * @return 有必填槽位返回 {@code true}
     */
    public static boolean hasRequiredSlots(String intent) {
        return REQUIRED.containsKey(intent);
    }
}
