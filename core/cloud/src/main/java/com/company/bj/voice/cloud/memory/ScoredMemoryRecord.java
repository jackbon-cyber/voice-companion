package com.company.bj.voice.cloud.memory;

import java.util.List;
import java.util.Optional;

/**
 * 带检索得分的记忆记录。
 *
 * <p><b>为什么需要它</b>：普通 {@link MemoryRecord} 只带正文与权重，
 * 检索方拿不到"这条记忆与本次提问有多相关"。
 * 于是一条**排在第一位但其实不相关**的记忆，与一条排在第三位但正是答案的记忆，
 * 在调用方眼里没有区别 ——
 * 调用方只能"取第一条"，而这恰恰是产品真正回复用户的那一条。
 *
 * <p>有了得分，调用方才能区分三件事：
 * <ol>
 *   <li>命中的确相关（得分高）—— 可以当事实陈述；</li>
 *   <li>命中但不够相关（得分低）—— 宁可如实说"没有记录"，也不猜；</li>
 *   <li>第一条与第二条得分接近（区分度不足）—— 模型分不清，说不准就不说。</li>
 * </ol>
 *
 * <p><b>得分口径</b>：{@code score = 1 / (1 + distance)}，越大越相关，
 * 与 {@code ChromaQueryResultReader#toScore} 一致。
 * 之所以复用同一个公式而不是另立一套，是因为"同一份数据在两个入口算出不同得分"
 * 是极难定位的一类问题。
 *
 * @param record  记忆记录
 * @param score   检索得分，越大越相关；未知时为负值
 */
public record ScoredMemoryRecord(MemoryRecord record, double score) {

    /**
     * 得分未知时的标记值。
     *
     * <p>用负值而不是 0，是因为 0 是一个**合法**的得分（距离无穷大时），
     * 用它当"未知"会让"确实不相关"与"没有得分信息"无法区分。
     */
    public static final double UNKNOWN_SCORE = -1.0;

    /**
     * 判断得分是否已知。
     *
     * @return 得分已知返回 {@code true}
     */
    public boolean scored() {
        return score >= 0.0;
    }

    /**
     * 返回记录正文。
     *
     * @return 正文
     */
    public String content() {
        return record.content();
    }

    /**
     * 返回记录标识。
     *
     * @return 记录标识
     */
    public String id() {
        return record.id();
    }

    /**
     * 提取正文列表。
     *
     * @param records 带得分的记录列表
     * @return 正文列表
     */
    public static List<String> contentsOf(List<ScoredMemoryRecord> records) {
        return records == null
                ? List.of()
                : records.stream().map(ScoredMemoryRecord::content).toList();
    }

    /**
     * 包装一条不带得分的记录。
     *
     * @param record 记忆记录
     * @return 得分未知的包装
     */
    public static ScoredMemoryRecord unscored(MemoryRecord record) {
        return new ScoredMemoryRecord(record, UNKNOWN_SCORE);
    }

    /**
     * 返回得分最高的一条。
     *
     * @param records 带得分的记录列表
     * @return 得分最高的一条；没有记录时为空
     */
    public static Optional<ScoredMemoryRecord> best(List<ScoredMemoryRecord> records) {
        if (records == null || records.isEmpty()) {
            return Optional.empty();
        }
        return records.stream()
                .max((left, right) -> Double.compare(left.score(), right.score()));
    }
}
