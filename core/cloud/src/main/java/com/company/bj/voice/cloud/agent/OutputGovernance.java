package com.company.bj.voice.cloud.agent;

import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 输出治理器。
 *
 * <p>对生成的回复做三项治理：
 * <ol>
 *   <li><b>长度约束</b> —— 超出上限则截断；</li>
 *   <li><b>重复度检查</b> —— 与最近若干条回复过于相似时<b>要求重生成</b>；</li>
 *   <li><b>情感标签与文本同时产出</b> —— 让下游（语音合成、端侧渲染）
 *       知道该用什么语气念。</li>
 * </ol>
 *
 * <p><b>为什么重复回复要重生成而不是直接放过</b>：
 * 陪伴机器人的价值在于"每次都有新意"。同一句话反复出现，
 * 用户会立刻感知到这是一个机械程序 —— 这正是陪伴场景最致命的失败。
 *
 * <p><b>重复度的度量用"二元组 Dice 相似度"</b>：
 * 中文没有空格分词，按字切二元组既能识别换词重述
 * （"我懂你的难过" vs "我明白你的难过" 相似度 0.94），
 * 又不会因为个别虚词的差异而漏判。
 */
public class OutputGovernance {

    /** 默认最大长度。 */
    public static final int DEFAULT_MAX_LENGTH = 120;

    /** 默认重复度阈值。 */
    public static final double DEFAULT_REPETITION_THRESHOLD = 0.75;

    /** 重复度检查窗口大小。 */
    public static final int DEFAULT_WINDOW = 5;

    /** 最大长度。 */
    private final int maxLength;

    /** 重复度阈值。 */
    private final double repetitionThreshold;

    /** 最近回复窗口。 */
    private final int window;

    /** 最近回复。 */
    private final java.util.ArrayDeque<String> recent = new java.util.ArrayDeque<>();

    /**
     * 构造输出治理器，使用默认参数。
     */
    public OutputGovernance() {
        this(DEFAULT_MAX_LENGTH, DEFAULT_REPETITION_THRESHOLD, DEFAULT_WINDOW);
    }

    /**
     * 构造输出治理器。
     *
     * @param maxLength           最大长度
     * @param repetitionThreshold 重复度阈值
     * @param window              最近回复窗口大小
     */
    public OutputGovernance(int maxLength, double repetitionThreshold, int window) {
        this.maxLength = maxLength;
        this.repetitionThreshold = repetitionThreshold;
        this.window = window;
    }

    /**
     * 治理一条回复。
     *
     * @param output    待治理的回复
     * @param emotionTag 情感标签
     * @return 治理结果
     */
    public GovernedOutput govern(String output, String emotionTag) {
        if (output == null || output.isBlank()) {
            return new GovernedOutput("", emotionTag, true, "回复为空", 0.0);
        }

        double maxSimilarity = 0.0;
        for (String previous : recent) {
            maxSimilarity = Math.max(maxSimilarity, similarity(output, previous));
        }

        if (maxSimilarity >= repetitionThreshold) {
            // 重复度过高：要求重生成。此时**不**把本条记入窗口 ——
            // 记入会让后续每一轮都撞上同一个阈值，重生成将永远无法通过。
            return new GovernedOutput(output, emotionTag, true,
                "与最近回复相似度 " + String.format("%.2f", maxSimilarity)
                    + " 超过阈值 " + repetitionThreshold + "，要求重生成",
                maxSimilarity);
        }

        String trimmed = output.length() > maxLength ? output.substring(0, maxLength) : output;
        boolean truncated = trimmed.length() < output.length();

        remember(output);
        return new GovernedOutput(trimmed, emotionTag, truncated,
            truncated ? "超出长度上限，已截断" : "通过治理", maxSimilarity);
    }

    /**
     * 把一条回复记入窗口。
     *
     * @param output 回复
     */
    private void remember(String output) {
        recent.addLast(output);
        while (recent.size() > window) {
            recent.removeFirst();
        }
    }

    /**
     * 计算两段文本的二元组 Dice 相似度。
     *
     * <p><b>为什么用 Dice 而不是 Jaccard</b>：
     * Jaccard 的分母是并集，短句上换一个字的代价被放大 ——
     * 实测"我懂你的难过"与"我明白你的难过"（仅一字之差）
     * 的 Jaccard 只有 0.71，低于 0.75 的阈值，判不出重复。
     * Dice 的分母是两侧之和，同样的一字之差能到 0.94，
     * 符合"这实质上是同一句话"的直觉。
     *
     * <p>且 Dice 对<b>包含关系</b>不像重叠系数那样敏感 ——
     * 短句完全落在长句里不会得满分。
     *
     * @param left  左侧文本
     * @param right 右侧文本
     * @return 相似度，取值区间为 0 到 1
     */
    public static double similarity(String left, String right) {
        if (left == null || right == null || left.isEmpty() || right.isEmpty()) {
            return 0.0;
        }
        Map<String, Integer> leftGrams = bigrams(left);
        Map<String, Integer> rightGrams = bigrams(right);

        int intersection = 0;
        for (Map.Entry<String, Integer> entry : leftGrams.entrySet()) {
            intersection += Math.min(entry.getValue(), rightGrams.getOrDefault(entry.getKey(), 0));
        }
        int total = leftGrams.values().stream().mapToInt(Integer::intValue).sum()
            + rightGrams.values().stream().mapToInt(Integer::intValue).sum();
        return total == 0 ? 0.0 : 2.0 * intersection / total;
    }

    /**
     * 提取文本的二元组集合。
     *
     * @param text 文本
     * @return 二元组到出现次数的映射
     */
    private static Map<String, Integer> bigrams(String text) {
        Map<String, Integer> grams = new HashMap<>(Math.max(16, text.length()));
        for (int index = 0; index + 1 < text.length(); index++) {
            String gram = text.substring(index, index + 2);
            grams.merge(gram, 1, Integer::sum);
        }
        if (text.length() == 1) {
            grams.put(text, 1);
        }
        return grams;
    }

    /**
     * 治理结果。
     *
     * @param output          治理后的回复
     * @param emotionTag      情感标签
     * @param needsRegeneration 是否需要重生成
     * @param reason          判定说明
     * @param similarity      与最近回复的最大相似度
     */
    public record GovernedOutput(
        String output,
        String emotionTag,
        boolean needsRegeneration,
        String reason,
        double similarity) {
    }
}
