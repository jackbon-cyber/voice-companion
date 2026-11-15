package com.company.bj.voice.cloud.safety;

import java.util.ArrayList;
import java.util.List;

/**
 * 句级流式审核器。
 *
 * <p>回复<b>按句生成、逐句送审</b>：只有通过审核的句子才会被下发，
 * 未通过的句子被替换为安全话术。
 *
 * <p><b>为什么逐句而不是整段审</b>：
 * <ul>
 *   <li>整段审会让用户在听完<b>整段</b>之后才发现内容被拦下 ——
 *       语音场景下这等于"说了不该说的话"；</li>
 *   <li>逐句审可以在<b>还没说出</b>风险内容时就拦下它。</li>
 * </ul>
 *
 * <p><b>代价</b>：审核次数增加（每句一次），首包延迟上升。
 * 这个代价由任务 8.4 单独核算进首包预算。
 */
public class StreamingSentenceReviewer {

    /** 审核器。 */
    private final SafetyReviewer reviewer;

    /** 未通过时使用的安全话术。 */
    private final String safePhrase;

    /** 已通过审核的句子。 */
    private final List<String> approved = new ArrayList<>();

    /** 被拦下的句子数。 */
    private int blockedCount;

    /** 审核耗时累计（毫秒）。 */
    private long reviewMillis;

    /**
     * 构造句级流式审核器。
     *
     * @param reviewer   审核器
     * @param safePhrase 未通过时使用的安全话术
     */
    public StreamingSentenceReviewer(SafetyReviewer reviewer, String safePhrase) {
        this.reviewer = reviewer;
        this.safePhrase = safePhrase;
    }

    /**
     * 审核一句并返回可下发的内容。
     *
     * @param sentence 待审核句子
     * @return 审核结果
     */
    public SentenceResult reviewSentence(String sentence) {
        if (sentence == null || sentence.isBlank()) {
            return new SentenceResult("", true, "空句子");
        }

        long start = System.nanoTime();
        SafetyReviewer.Review review = reviewer.reviewOutput(sentence);
        reviewMillis += (System.nanoTime() - start) / 1_000_000;

        if (review.blocked()) {
            blockedCount++;
            // 被拦下的句子**不下发**，改用安全话术。
            return new SentenceResult(safePhrase, false, review.reason());
        }

        approved.add(sentence);
        return new SentenceResult(sentence, true, review.reason());
    }

    /**
     * 返回已通过审核的句子。
     *
     * @return 句子列表
     */
    public List<String> approvedSentences() {
        return List.copyOf(approved);
    }

    /**
     * 返回被拦下的句子数。
     *
     * @return 数量
     */
    public int blockedCount() {
        return blockedCount;
    }

    /**
     * 返回累计审核耗时（毫秒）。
     *
     * @return 毫秒数
     */
    public long reviewMillis() {
        return reviewMillis;
    }

    /**
     * 单句审核结果。
     *
     * @param content 可下发的内容
     * @param passed  是否通过审核
     * @param reason  判定说明
     */
    public record SentenceResult(String content, boolean passed, String reason) {
    }
}
