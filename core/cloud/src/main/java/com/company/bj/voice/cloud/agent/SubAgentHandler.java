package com.company.bj.voice.cloud.agent;

import java.util.List;

/**
 * 子智能体处理器端口。
 *
 * <p>一个子智能体负责一类意图的<b>具体处理</b>：主控负责编排，
 * 具体怎么做交给各自独立的处理器。
 *
 * <p><b>为什么拆成独立处理器</b>：六类子智能体的职责差异极大
 * （角色扮演要维持人设、共情要接住情绪、安全审核要拦下来），
 * 塞进一个大方法里会变成连绵的 if 分支，每加一类都要重读全部分支。
 */
public interface SubAgentHandler {

    /**
     * 处理一个意图。
     *
     * @param request 处理请求
     * @return 处理结果
     */
    SubAgentResult handle(SubAgentRequest request);

    /**
     * 返回该处理器负责的意图。
     *
     * @return 意图标识列表
     */
    List<String> supportedIntents();

    /**
     * 返回该处理器的<b>输出优先级</b>。
     *
     * <p>数值越小优先级越高。裁决器据此在多个处理器都给出输出时选谁。
     *
     * @return 优先级数值；越小越优先
     */
    int priority();

    /**
     * 处理请求。
     *
     * @param intent    意图标识
     * @param text      用户文本
     * @param context   会话上下文（装配好的提示词）
     * @param memories  召回的记忆片段
     */
    record SubAgentRequest(
        String intent, String text, String context, List<String> memories) {
    }

    /**
     * 处理结果。
     *
     * @param output       生成的回复文本
     * @param intent      产生的意图
     * @param safetyLevel  安全等级
     * @param emotionTag  情感标签
     * @param rejected     是否被安全层拦下
     * @param reason       说明；被拦下时给出原因
     */
    record SubAgentResult(
        String output, String intent, SafetyLevel safetyLevel, String emotionTag,
        boolean rejected, String reason) {

        /**
         * 构造一个正常的处理结果。
         *
         * @param output      回复文本
         * @param intent     意图标识
         * @param emotionTag 情感标签
         * @return 处理结果
         */
        public static SubAgentResult of(String output, String intent, String emotionTag) {
            return new SubAgentResult(output, intent, SafetyLevel.SAFE, emotionTag, false, null);
        }

        /**
         * 构造一个被安全层拦下的结果。
         *
         * @param intent 意图标识
         * @param reason 拦截原因
         * @param safetyLevel 安全等级
         * @return 处理结果
         */
        public static SubAgentResult rejected(
            String intent, String reason, SafetyLevel safetyLevel) {
            return new SubAgentResult("", intent, safetyLevel, null, true, reason);
        }
    }

    /**
     * 安全等级。
     */
    enum SafetyLevel {

        /** 安全。 */
        SAFE,

        /** 需注意（敏感但不需拦截）。 */
        CAUTION,

        /** 高危（必须拦下）。 */
        HIGH
    }
}
