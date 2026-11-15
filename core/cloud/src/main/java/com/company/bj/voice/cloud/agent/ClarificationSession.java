package com.company.bj.voice.cloud.agent;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 多轮澄清会话。
 *
 * <p>用户说的信息不全时（"把声音调一下"没说调到多少），
 * 机器人追问缺失的槽位，用户的回答<b>增量合并</b>进已有的槽位集合，
 * 而不是替换它。
 *
 * <p><b>为什么必须增量合并</b>：用户常常只回答被问的那一项
 * （"调到六十"），而不是重说整句。若用替换语义，
 * 上一轮已经确认的意图与已填的槽位会被丢掉，
 * 机器人就会反复问同一个问题 —— 这是最让人恼火的对话体验。
 *
 * <p><b>轮次上限</b>：追问超过上限就<b>停止追问</b>，
 * 用最可能的候选值继续（而不是无限追问下去）。
 * 无限追问会把一次普通的音量调节变成审讯。
 */
public class ClarificationSession {

    /** 默认最大追问轮次。 */
    public static final int DEFAULT_MAX_ROUNDS = 3;

    /** 各作用域的澄清状态。 */
    private final Map<String, State> sessions = new LinkedHashMap<>();

    /** 最大追问轮次。 */
    private final int maxRounds;

    /**
     * 构造澄清会话管理器。
     */
    public ClarificationSession() {
        this(DEFAULT_MAX_ROUNDS);
    }

    /**
     * 构造澄清会话管理器。
     *
     * @param maxRounds 最大追问轮次
     */
    public ClarificationSession(int maxRounds) {
        this.maxRounds = maxRounds;
    }

    /**
     * 开始或继续一次澄清。
     *
     * @param scopeKey     作用域键
     * @param intent       已确定的意图
     * @param knownSlots   本轮已识别到的槽位
     * @param missingSlots 仍缺失的槽位
     * @param candidates   各缺失槽位的候选值（按可能性降序）
     * @return 澄清结果
     */
    public ClarificationOutcome clarify(
        String scopeKey,
        String intent,
        Map<String, String> knownSlots,
        List<String> missingSlots,
        Map<String, List<String>> candidates) {

        State state = sessions.computeIfAbsent(scopeKey, key -> new State());

        if (!java.util.Objects.equals(state.intent, intent)) {
            // 意图变了说明用户改主意了，这一轮要重新问，
            // 不能把上一个意图的槽位带过来 —— 那是"张冠李戴"。
            state.slots.clear();
            state.rounds = 0;
        }
        state.intent = intent;
        state.rounds++;

        // 增量合并：只覆盖本轮明确给出的槽位，其余保留。
        if (knownSlots != null) {
            knownSlots.forEach(state.slots::putIfAbsent);
        }

        List<String> stillMissing = new ArrayList<>();
        for (String slot : missingSlots == null ? List.<String>of() : missingSlots) {
            if (!state.slots.containsKey(slot)) {
                stillMissing.add(slot);
            }
        }

        if (stillMissing.isEmpty()) {
            // 槽位补齐：结束澄清并清理会话状态。
            Map<String, String> resolved = new LinkedHashMap<>(state.slots);
            sessions.remove(scopeKey);
            return new ClarificationOutcome(
                ClarificationStatus.RESOLVED, intent, resolved, List.of(), state.rounds,
                "槽位已补齐");
        }

        if (state.rounds >= maxRounds) {
            // 达到上限：不再追问，用最可能的候选值继续。
            Map<String, String> filled = new LinkedHashMap<>(state.slots);
            List<String> assumed = new ArrayList<>();
            for (String slot : stillMissing) {
                List<String> options = candidates == null ? null : candidates.get(slot);
                if (options != null && !options.isEmpty()) {
                    filled.put(slot, options.get(0));
                    assumed.add(slot);
                }
            }
            Map<String, String> resolved = new LinkedHashMap<>(filled);
            sessions.remove(scopeKey);
            return new ClarificationOutcome(
                ClarificationStatus.ASSUMED, intent, resolved, assumed, state.rounds,
                "追问已达上限，采用最可能的值继续");
        }

        return new ClarificationOutcome(
            ClarificationStatus.NEEDS_CLARIFICATION, intent, new LinkedHashMap<>(state.slots),
            stillMissing, state.rounds, "需要追问缺失的槽位");
    }

    /**
     * 结束某作用域的澄清会话。
     *
     * @param scopeKey 作用域键
     */
    public void end(String scopeKey) {
        sessions.remove(scopeKey);
    }

    /**
     * 判断某作用域是否有进行中的澄清。
     *
     * @param scopeKey 作用域键
     * @return 有进行中的澄清返回 {@code true}
     */
    public boolean inProgress(String scopeKey) {
        return sessions.containsKey(scopeKey);
    }

    /**
     * 澄清状态。
     */
    public enum ClarificationStatus {

        /** 仍需追问。 */
        NEEDS_CLARIFICATION,

        /** 槽位已补齐。 */
        RESOLVED,

        /** 追问达上限，采用候选值。 */
        ASSUMED
    }

    /**
     * 澄清结果。
     *
     * @param status        澄清状态
     * @param intent        意图标识
     * @param slots         合并后的槽位
     * @param missingSlots  仍缺失（或被假定）的槽位
     * @param rounds        已追问轮次
     * @param reason        说明
     */
    public record ClarificationOutcome(
        ClarificationStatus status,
        String intent,
        Map<String, String> slots,
        List<String> missingSlots,
        int rounds,
        String reason) {

        /**
         * 判断是否还需继续追问。
         *
         * @return 需要继续追问返回 {@code true}
         */
        public boolean needsMore() {
            return status == ClarificationStatus.NEEDS_CLARIFICATION;
        }

        /**
         * 判断是否已可继续执行。
         *
         * @return 可继续执行返回 {@code true}
         */
        public boolean executable() {
            return status == ClarificationStatus.RESOLVED || status == ClarificationStatus.ASSUMED;
        }
    }

    /** 澄清会话状态。 */
    private static final class State {
        private String intent;
        private int rounds;
        private final Map<String, String> slots = new LinkedHashMap<>();
    }
}
