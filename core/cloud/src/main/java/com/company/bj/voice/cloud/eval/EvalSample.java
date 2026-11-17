package com.company.bj.voice.cloud.eval;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 评测样本。
 *
 * <p><b>三个字段的分工</b>：
 * <ul>
 *   <li>{@code input} —— 送给系统的<b>问句</b>；</li>
 *   <li>{@code expected} —— 期望系统给出的<b>答案</b>；</li>
 *   <li>{@code corpus} —— 这条样本在<b>评测时预先写入记忆库</b>的原文。
 *       为 {@code null} 时表示直接用 {@code input} 作为记忆原文。</li>
 * </ul>
 *
 * <p><b>为什么要单独一个 {@code corpus} 字段</b>：
 * 记忆召回要测的是"用<b>另一种说法</b>问，能不能找回那条记忆"。
 * 若问句与记忆原文完全相同，召回率必然是 1.0 ——
 * 那测的是字符串相等，不是语义召回能力。
 * 两者分开后，问句与记忆原文是<b>不同的表述</b>，
 * 召回率才真正反映嵌入与检索的质量。
 *
 * @param dimension 评测维度
 * @param input     输入（问句）
 * @param expected  期望结果
 * @param corpus    评测时预先写入记忆库��原文；为空时用 {@code input}
 * @param metadata  附加信息
 */
public record EvalSample(
    EvalDimension dimension, String input, String expected, String corpus,
    Map<String, String> metadata) {

    /**
     * 构造一个不带附加信息的样本。
     *
     * @param dimension 评测维度
     * @param input     输入
     * @param expected  期望结果
     * @return 样本
     */
    public static EvalSample of(EvalDimension dimension, String input, String expected) {
        return new EvalSample(dimension, input, expected, null, Map.of());
    }

    /**
     * 构造一个带记忆原文的样本。
     *
     * @param dimension 评测维度
     * @param input     输入（问句）
     * @param expected  期望结果
     * @param corpus    评测时预先写入记忆库的原文
     * @return 样本
     */
    public static EvalSample withCorpus(
        EvalDimension dimension, String input, String expected, String corpus) {
        return new EvalSample(dimension, input, expected, corpus, Map.of());
    }

    /**
     * 返回本条样本的记忆原文。
     *
     * @return 记忆原文；未单独指定时回落为 {@code input}
     */
    public String corpusOrInput() {
        return corpus == null || corpus.isBlank() ? input : corpus;
    }
}
