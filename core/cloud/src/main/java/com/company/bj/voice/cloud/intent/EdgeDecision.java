package com.company.bj.voice.cloud.intent;

import java.util.Map;

/**
 * 端侧判定结果。
 *
 * <p>由端侧规则表或端侧小模型产生，上报给云端作为三级判定的第一级输入。
 *
 * @param intent     意图标识
 * @param confidence 置信度，取值区间为 0 到 1
 * @param slots      已识别到的槽位
 */
public record EdgeDecision(String intent, double confidence, Map<String, String> slots) {

    /**
     * 构造一个不携带槽位的端侧判定结果。
     *
     * @param intent     意图标识
     * @param confidence 置信度
     * @return 端侧判定结果
     */
    public static EdgeDecision of(String intent, double confidence) {
        return new EdgeDecision(intent, confidence, Map.of());
    }
}
