package com.company.bj.voice.cloud.safety;

/**
 * 首包预算核算器。
 *
 * <p>把安全审核引入的额外延迟纳入首包预算核算。
 *
 * <p><b>审核本身会吃掉首包预算</b>：如果审核耗时 80 ms 而首包预算只有 50 ms，
 * 那么无论生成多快，用户都感知不到"快"。不核算这件事，
 * 就会在压测里发现"首包延迟超标"，却查不出是审核造成的。
 *
 * <p><b>预算不足时的处置是"降级审核粒度"而不是"超时放行"</b>：
 * 超时放行等于让审核形同虚设 —— 那还不如不做审核。
 * 降级到"整段审"或"只审高风险类别"能保住安全性的一部分，
 * 同时把延迟拉回预算内。
 */
public class FirstPacketBudget {

    /** 首包预算（毫秒）。 */
    private final long budgetMillis;

    /** 审核器。 */
    private final SafetyReviewer reviewer;

    /** 已消耗的审核耗时（毫秒）。 */
    private long reviewMillis;

    /**
     * 构造首包预算核算器。
     *
     * @param budgetMillis 首包预算（毫秒）
     * @param reviewer     审核器
     */
    public FirstPacketBudget(long budgetMillis, SafetyReviewer reviewer) {
        this.budgetMillis = budgetMillis;
        this.reviewer = reviewer;
    }

    /**
     * 审核一句话并记账审核耗时。
     *
     * @param sentence 待审核句子
     * @return 审核结论
     */
    public SafetyReviewer.Review reviewAndAccount(String sentence) {
        long start = System.nanoTime();
        SafetyReviewer.Review review = reviewer.reviewOutput(sentence);
        reviewMillis += (System.nanoTime() - start) / 1_000_000;
        return review;
    }

    /**
     * 记录一段已发生的审核耗时。
     *
     * @param millis 毫秒数
     */
    public void accountReviewMillis(long millis) {
        reviewMillis += millis;
    }

    /**
     * 返回剩余的审核预算。
     *
     * @return 剩余毫秒数
     */
    public long remainingBudgetMillis() {
        return Math.max(0, budgetMillis - reviewMillis);
    }

    /**
     * 判断审核耗时是否已超出预算。
     *
     * @return 超出返回 {@code true}
     */
    public boolean overBudget() {
        return reviewMillis > budgetMillis;
    }

    /**
     * 判断是否还能再做一次审核。
     *
     * <p>判据是"剩余预算至少够一次典型审核"——
     * 典型审核耗时取 5 ms（关键词表的实测量级）。
     *
     * @return 还能审核返回 {@code true}
     */
    public boolean canReviewMore() {
        return remainingBudgetMillis() >= TYPICAL_REVIEW_MILLIS;
    }

    /**
     * 一次典型审核的耗时估计（毫秒）。 */
    public static final long TYPICAL_REVIEW_MILLIS = 5;

    /**
     * 返回首包预算。
     *
     * @return 预算毫秒数
     */
    public long budgetMillis() {
        return budgetMillis;
    }

    /**
     * 返回累计审核耗时。
     *
     * @return 毫秒数
     */
    public long reviewMillis() {
        return reviewMillis;
    }
}
