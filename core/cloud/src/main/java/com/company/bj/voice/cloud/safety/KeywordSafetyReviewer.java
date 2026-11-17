package com.company.bj.voice.cloud.safety;

import java.util.List;
import java.util.Map;

/**
 * 关键词驱动的安全审核器。
 *
 * <p>基于关键词表的确定性审核，零延迟、零依赖、可复现。
 *
 * <p><b>为什么不用模型做审核</b>：审核是<b>必须拦下</b>的关口，
 * 漏判的代价远高于误判（误判只是回复得保守一点，漏判是放任危险内容通过）。
 * 关键词表的漏判率可以通过持续补充词表压低，
 * 而模型审核的漏判不可预测、不可复现、也无法审计。
 *
 * <p><b>危机信号的判定采用"多信号累积"</b>：单一词语（如"绝望"）
 * 不构成危机，但"没意思" + "活着" + "撑不下去"这类组合才是。
 * 单词触发会把正常的情绪表达误判为危机 —— 陪伴场景里最忌讳的误判。
 */
public class KeywordSafetyReviewer implements SafetyReviewer {

    /** 危机信号词。
     *
     * <p><b>词表要覆盖"同义与否定式"表述</b>：只收"不想活"会漏掉
     * "别活了""活不下去算了"这类更口语的说法 —— 而口语才是真实用户
     * 说出危机信号时的样子。漏一个词表条目就是漏一次危机干预。
     *
     * <p><b>也要覆盖"插入修饰语"的变体</b>：中文里同一个意思可以有很多种说法，
     * "结束生命"与"结束<b>自己的</b>生命"意思完全一样，但字面不同。
     * 词表若只收前者，后者在审核里会<b>完全不可见</b> ——
     * 这正是评测集第 2 组暴露出来的真实漏判。 */
    private static final List<String> CRISIS_SIGNALS = List.of(
        "不想活", "别活", "活不下去", "想死", "不想死", "去死", "自杀", "自残",
        "结束生命", "结束自己的生命", "结束我的生命", "结束此生", "了结自己", "了结此生",
        "死了算了", "别活了", "活没意思", "活着没意思", "活着真的没意思", "活着没意思了",
        "没意思了", "撑不下去", "解脱了", "消失算了", "一了百了", "了结自己");

    /** 危机信号词的辅助线索。 */
    private static final List<String> CRISIS_HINTS = List.of(
        "活着", "活着好累", "没人爱", "没人在乎", "孤独", "绝望",
        "没有意义", "撑不住", "熬不下去", "想解脱", "没意思", "压力太大", "扛不住");

    /** 一般敏感内容词。 */
    private static final List<String> SENSITIVE_TERMS = List.of(
        "赌博", "毒品", "偷", "诈骗", "抢劫");

    /** 专业领域词（陪伴机器人不应给确定答案）。 */
    private static final List<String> PROFESSIONAL_TERMS = List.of(
        "吃什么药", "什么药", "诊断", "确诊", "遗嘱", "投资多少", "买什么股票");

    /** 危机场景下的求助渠道提示。 */
    private final String crisisGuidance;

    /**
     * 返回审核器使用的全部关键词。
     *
     * <p>与意图示例句库同理：暴露出来供评测集做语料交集检查，
     * 避免测试里抄一份会过期的拷贝。
     *
     * @return 全部关键词
     */
    public static List<String> keywords() {
        return List.of(
            CRISIS_SIGNALS, CRISIS_HINTS, SENSITIVE_TERMS, PROFESSIONAL_TERMS)
            .stream().flatMap(List::stream).toList();
    }

    /**
     * 构造关键词审核器。
     *
     * @param crisisGuidance 危机场景下的求助渠道提示
     */
    public KeywordSafetyReviewer(String crisisGuidance) {
        this.crisisGuidance = crisisGuidance;
    }

    @Override
    public Review reviewInput(String text) {
        return review(text);
    }

    @Override
    public Review reviewOutput(String text) {
        return review(text);
    }

    /**
     * 执行审核。
     *
     * @param text 待审核文本
     * @return 审核结论
     */
    private Review review(String text) {
        if (text == null || text.isBlank()) {
            return Review.safe();
        }
        String normalized = text.toLowerCase();

        if (containsAny(normalized, CRISIS_SIGNALS)) {
            return new Review(RiskLevel.HIGH, true, "命中危机信号词", RiskCategory.CRISIS);
        }

        if (countHints(normalized) >= CRISIS_HINT_THRESHOLD) {
            return new Review(RiskLevel.HIGH, true, "多个危机辅助线索同时出现", RiskCategory.CRISIS);
        }

        if (containsAny(normalized, PROFESSIONAL_TERMS)) {
            return new Review(RiskLevel.MEDIUM, false, "涉及专业领域，应引导至专业渠道",
                RiskCategory.PROFESSIONAL);
        }

        if (containsAny(normalized, SENSITIVE_TERMS)) {
            return new Review(RiskLevel.MEDIUM, false, "涉及敏感话题", RiskCategory.SENSITIVE);
        }

        if (countHints(normalized) >= 1) {
            return new Review(RiskLevel.LOW, false, "出现情绪线索，需谨慎回应", RiskCategory.SENSITIVE);
        }

        return Review.safe();
    }

    /** 危机辅助线索的累积阈值。 */
    private static final int CRISIS_HINT_THRESHOLD = 2;

    /**
     * 判断文本是否包含任一关键词。
     *
     * @param normalized 归一化文本
     * @param terms      关键词列表
     * @return 命中返回 {@code true}
     */
    private boolean containsAny(String normalized, List<String> terms) {
        for (String term : terms) {
            if (normalized.contains(term.toLowerCase())) {
                return true;
            }
        }
        return false;
    }

    /**
     * 统计危机辅助线索的命中个数。
     *
     * @param normalized 归一化文本
     * @return 命中个数
     */
    private int countHints(String normalized) {
        int count = 0;
        for (String hint : CRISIS_HINTS) {
            if (normalized.contains(hint.toLowerCase())) {
                count++;
            }
        }
        return count;
    }

    /**
     * 返回危机场景下的求助渠道提示。
     *
     * @return 求助渠道提示
     */
    public String crisisGuidance() {
        return crisisGuidance;
    }
}
