package com.company.bj.voice.cloud.agent;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;

/**
 * 多子智能体输出的优先级裁决器。
 *
 * <p>多个处理器可能对同一轮都给出输出（例如用户说"我今天很难过，
 * 你能放首歌吗"——共情处理器和播放处理器都会应答）。
 * 裁决器按<b>固定优先级</b>选一个：安全 &gt; 事实 &gt; 人设 &gt; 情绪。
 *
 * <p><b>为什么是"选一个"而不是"都发出去"</b>：设备一次只能播一条语音。
 * 都发出去意味着用户听到两段互相抢戏的话，那是陪伴体验最差的形态。
 *
 * <p><b>优先级放在数据里而不是 if 链里</b>：裁决顺序由每个处理器的
 * {@link SubAgentHandler#priority()} 决定，改顺序只需改数字。
 */
public class SubAgentArbitrator {

    /** 安全类的优先级。数值越小越优先。 */
    public static final int PRIORITY_SAFETY = 10;

    /** 事实类的优先级。 */
    public static final int PRIORITY_FACTUAL = 20;

    /** 人设类的优先级。 */
    public static final int PRIORITY_PERSONA = 30;

    /** 情绪类的优先级。 */
    public static final int PRIORITY_EMOTION = 40;

    /**
     * 在多个结果中裁决出最终输出。
     *
     * <p>裁决顺序：
     * <ol>
     *   <li><b>被拒的结果优先</b> —— 安全层拦下的内容不能被其他处理器"救回来"。
     *       这是最重要的一条：一个处理器判定"这句话不能说"，
     *       另一个处理器说"我可以说"，必须听前者的；</li>
     *   <li>否则按<b>安全等级</b>（HIGH &gt; CAUTION &gt; SAFE）；</li>
     *   <li>再按<b>处理器优先级</b>（数值小者胜）；</li>
     *   <li>最后按<b>结果顺序</b>（先注册者优先），保证结果稳定可复现。</li>
     * </ol>
     *
     * @param results 候选结果
     * @return 裁决后的结果；无候选时返回空
     */
    public ArbitrationResult arbitrate(List<Candidate> results) {
        if (results == null || results.isEmpty()) {
            return new ArbitrationResult(null, List.of(), "无候选结果");
        }

        List<Candidate> sorted = new ArrayList<>(results);
        sorted.sort(Comparator
            .comparing(Candidate::rejected, Comparator.reverseOrder())
            .thenComparing(candidate -> candidate.result().safetyLevel().ordinal())
            .thenComparingInt(Candidate::priority)
            .thenComparingInt(Candidate::order));

        Candidate winner = sorted.get(0);
        List<String> discarded = new ArrayList<>();
        for (int index = 1; index < sorted.size(); index++) {
            discarded.add(sorted.get(index).intent());
        }

        String reason = winner.rejected()
            ? "被安全层拦下：" + winner.result().reason()
            : "按优先级选出 " + winner.intent();

        return new ArbitrationResult(winner.result(), discarded, reason);
    }

    /**
     * 一个候选结果。
     *
     * @param intent   意图标识
     * @param priority 处理器优先级
     * @param order    注册顺序，用于稳定排序
     * @param result   处理结果
     */
    public record Candidate(String intent, int priority, int order, SubAgentHandler.SubAgentResult result) {

        /**
         * 构造一个候选结果。
         *
         * @param intent   意图标识
         * @param priority 处理器优先级
         * @param order    注册顺序
         * @param result   处理结果
         * @return 候选结果
         */
        public static Candidate of(
            String intent, int priority, int order, SubAgentHandler.SubAgentResult result) {
            return new Candidate(intent, priority, order, result);
        }

        /**
         * 判断该结果是否被安全层拦下。
         *
         * @return 被拦下返回 {@code true}
         */
        public boolean rejected() {
            return result != null && result.rejected();
        }
    }

    /**
     * 裁决结果。
     *
     * @param result     胜出的结果；无候选时为空
     * @param discarded  被淘汰的意图标识
     * @param reason     裁决理由
     */
    public record ArbitrationResult(
        SubAgentHandler.SubAgentResult result, List<String> discarded, String reason) {

        /**
         * 判断是否有输出可供下发。
         *
         * @return 有可下发输出返回 {@code true}
         */
        public boolean hasOutput() {
            return result != null && !result.rejected()
                && result.output() != null && !result.output().isBlank();
        }
    }
}
