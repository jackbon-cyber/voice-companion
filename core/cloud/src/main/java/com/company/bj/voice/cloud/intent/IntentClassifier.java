package com.company.bj.voice.cloud.intent;

import java.util.List;

/**
 * 意图分类器端口。
 *
 * <p>云端意图三级判定的<b>第二级</b>：端侧未判定时调用本端口。
 *
 * <p>抽成接口而不是直接写死某个实现，是为了让"用本地嵌入做原型分类"
 * 与"用远端模型做分类"成为可替换的两种策略，
 * 新增实现不需要改动三级判定的编排逻辑（架构守则 A3）。
 */
public interface IntentClassifier {

    /**
     * 判定一段文本的意图。
     *
     * @param text 用户文本
     * @return 分类结果
     */
    Classification classify(String text);

    /**
     * 一次分类的结果。
     *
     * @param intent     意图标识；无法判定时为 {@link #UNKNOWN_INTENT}
     * @param confidence 置信度，取值区间为 0 到 1
     * @param slots      意图参数；未识别到时为空
     */
    record Classification(String intent, double confidence, java.util.Map<String, String> slots) {

        /**
         * 构造一个不携带槽位的分类结果。
         *
         * @param intent     意图标识
         * @param confidence 置信度
         * @return 分类结果
         */
        public static Classification of(String intent, double confidence) {
            return new Classification(intent, confidence, java.util.Map.of());
        }
    }

    /** 未知意图标识。 */
    String UNKNOWN_INTENT = "unknown";

    /**
     * 列出该分类器支持的意图。
     *
     * @return 意图标识列表
     */
    List<String> supportedIntents();
}
