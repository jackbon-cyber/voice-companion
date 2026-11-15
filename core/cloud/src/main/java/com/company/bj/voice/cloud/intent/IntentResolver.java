package com.company.bj.voice.cloud.intent;

import java.util.List;
import java.util.Map;

/**
 * 意图三级判定编排器。
 *
 * <p>三级依次为：
 * <ol>
 *   <li><b>端侧已判定</b> —— 端侧规则表或端侧小模型命中且置信度足够，
 *       云端直接采信，<b>不再调用模型</b>；</li>
 *   <li><b>云端模型分类</b> —— 端侧未命中时调用 {@link IntentClassifier}；</li>
 *   <li><b>未知意图</b> —— 两者都无法判定，进入澄清流程。</li>
 * </ol>
 *
 * <p><b>三级判定省的是延迟，不是准确率</b>：端侧已确定的事再送云端跑一遍模型，
 * 既增加首包延迟又增加云端负载。因此第一级是"命中即短路"。
 *
 * <p><b>槽位缺失的判定在第三级之后</b>：意图确定了但参数不全（例如要调音量
 * 却没说调到多少），此时不是"未知意图"，而是"已知意图 + 缺槽位"，
 * 交给澄清环节追问。把它混进"未知"会丢掉已确定的信息。
 */
public class IntentResolver {

    /** 端侧判定结果的置信度下限。低于该值时云端不复用端侧结论。 */
    public static final double MIN_EDGE_CONFIDENCE = 0.6;

    /** 意图分类器。 */
    private final IntentClassifier classifier;

    /**
     * 构造意图判定编排器。
     *
     * @param classifier 意图分类器
     */
    public IntentResolver(IntentClassifier classifier) {
        this.classifier = classifier;
    }

    /**
     * 执行三级判定。
     *
     * @param request 判定请求
     * @return 判定结果
     */
    public IntentResolution resolve(IntentRequest request) {
        EdgeDecision edge = request.edgeDecision();

        if (edge != null && edge.confidence() >= MIN_EDGE_CONFIDENCE
            && !IntentClassifier.UNKNOWN_INTENT.equals(edge.intent())) {
            // 第一级：端侧已确定，直接采信，不再调用云端模型。
            return IntentResolution.fromEdge(edge);
        }

        IntentClassifier.Classification classification = classifier.classify(request.text());

        if (IntentClassifier.UNKNOWN_INTENT.equals(classification.intent())) {
            return IntentResolution.unknown(request.text(), classification.confidence());
        }

        // 第二级：云端模型判定成功。缺槽位由澄清环节追问，
        // 但意图本身已经确定 —— 不能因为缺参数就丢掉意图。
        List<String> missingSlots = findMissingSlots(classification.intent(), classification.slots());

        if (!missingSlots.isEmpty()) {
            return IntentResolution.needsClarification(
                request.text(), classification.intent(), classification.confidence(),
                missingSlots, classification.slots());
        }

        return IntentResolution.resolved(
            request.text(), classification.intent(), classification.confidence(), classification.slots());
    }

    /**
     * 找出该意图缺失的槽位。
     *
     * @param intent 意图标识
     * @param slots  已识别到的槽位
     * @return 缺失的槽位名列表
     */
    private List<String> findMissingSlots(String intent, Map<String, String> slots) {
        List<String> required = SlotRequirements.requiredSlots(intent);
        if (required.isEmpty()) {
            return List.of();
        }
        return required.stream()
            .filter(slot -> slots == null || !slots.containsKey(slot))
            .toList();
    }

    /**
     * 一次意图判定的请求。
     *
     * @param text         用户文本
     * @param edgeDecision 端侧判定结果；端侧未判定时为 {@code null}
     */
    public record IntentRequest(String text, EdgeDecision edgeDecision) {

        /**
         * 构造一个没有端侧判定结果的请求。
         *
         * @param text 用户文本
         * @return 请求
         */
        public static IntentRequest of(String text) {
            return new IntentRequest(text, null);
        }
    }
}
