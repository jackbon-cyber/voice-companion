package com.company.bj.voice.cloud.intent;

import java.util.List;
import java.util.Map;

/**
 * 意图判定结果。
 *
 * @param intent      意图标识；未知意图为 {@link IntentClassifier#UNKNOWN_INTENT}
 * @param confidence  置信度
 * @param slots       已识别到的槽位
 * @param missingSlots 缺失的槽位；无需澄清时为空
 * @param source      判定来源
 * @param text        原始用户文本
 */
public record IntentResolution(
    String intent,
    double confidence,
    Map<String, String> slots,
    List<String> missingSlots,
    IntentSource source,
    String text) {

    /**
     * 判定来源。
     */
    public enum IntentSource {

        /** 端侧已判定，云端采信。 */
        EDGE,

        /** 云端模型判定。 */
        CLOUD_MODEL,

        /** 无法判定。 */
        UNKNOWN
    }

    /**
     * 构造一个已完全判定的结果。
     *
     * @param text       原始文本
     * @param intent     意图标识
     * @param confidence 置信度
     * @param slots      槽位
     * @return 判定结果
     */
    public static IntentResolution resolved(
        String text, String intent, double confidence, Map<String, String> slots) {
        return new IntentResolution(intent, confidence, Map.copyOf(slots), List.of(),
            IntentSource.CLOUD_MODEL, text);
    }

    /**
     * 构造一个来自端侧的判定结果。
     *
     * @param edge 端侧判定结果
     * @return 判定结果
     */
    public static IntentResolution fromEdge(EdgeDecision edge) {
        return new IntentResolution(edge.intent(), edge.confidence(), Map.copyOf(edge.slots()),
            List.of(), IntentSource.EDGE, null);
    }

    /**
     * 构造一个需要澄清的结果。
     *
     * @param text         原始文本
     * @param intent       意图标识
     * @param confidence   置信度
     * @param missingSlots 缺失的槽位
     * @param slots        已识别到的槽位
     * @return 判定结果
     */
    public static IntentResolution needsClarification(
        String text, String intent, double confidence,
        List<String> missingSlots, Map<String, String> slots) {
        return new IntentResolution(intent, confidence, Map.copyOf(slots), List.copyOf(missingSlots),
            IntentSource.CLOUD_MODEL, text);
    }

    /**
     * 构造一个未知意图的结果。
     *
     * @param text       原始文本
     * @param confidence 置信度
     * @return 判定结果
     */
    public static IntentResolution unknown(String text, double confidence) {
        return new IntentResolution(IntentClassifier.UNKNOWN_INTENT, confidence, Map.of(), List.of(),
            IntentSource.UNKNOWN, text);
    }

    /**
     * 判断意图是否已确定。
     *
     * @return 意图已确定返回 {@code true}
     */
    public boolean resolved() {
        return !IntentClassifier.UNKNOWN_INTENT.equals(intent);
    }

    /**
     * 判断是否需要澄清追问。
     *
     * @return 需要澄清返回 {@code true}
     */
    public boolean needsClarification() {
        return !missingSlots.isEmpty();
    }
}
