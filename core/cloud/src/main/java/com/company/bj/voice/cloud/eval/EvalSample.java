package com.company.bj.voice.cloud.eval;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 评测样本。
 *
 * <p><b>五个字段的分工</b>：
 * <ul>
 *   <li>{@code input} —— 送给系统的<b>问句</b>；</li>
 *   <li>{@code expected} —— 期望系统给出的<b>结果</b>；</li>
 *   <li>{@code corpus} —— 这条样本在<b>评测时预先写入记忆库</b>的原文。
 *       为 {@code null} 时表示直接用 {@code input} 作为记忆原文；</li>
 *   <li>{@code expectedContent} —— <b>期望系统说出的记忆内容</b>。
 *       为 {@code null} 时表示"库里没有这条记忆"，即期望系统<b>拒答</b>。</li>
 *   <li>{@code metadata} —— 附加信息。</li>
 * </ul>
 *
 * <p><b>为什么要单独一个 {@code corpus} 字段</b>：
 * 记忆召回要测的是"用<b>另一种说法</b>问，能不能找回那条记忆"。
 * 若问句与记忆原文完全相同，召回率必然是 1.0 ——
 * 那测的是字符串相等，不是语义召回能力。
 * 两者分开后，问句与记忆原文是<b>不同的表述</b>，
 * 召回率才真正反映嵌入与检索的质量。
 *
 * <p><b>为什么要有 {@code expectedContent} 与 {@code corpus} 两个字段</b>：
 * 记忆作答维度要区分三种结果 ——
 * 「说了期望的那条」「说了另一条」「库里没有这条」。
 * 只有 {@code corpus} 时，"库里没有这条"与"库里这条被答错"
 * 都会退化成"系统说的话不是期望内容"，两者性质完全不同：
 * 前者是<b>正确行为</b>，后者是<b>严重失败</b>。
 * 把 {@code expectedContent} 留空，就把"库里没有这条"显式标了出来。
 *
 * @param dimension 评测维度
 * @param input     输入（问句）
 * @param expected  期望结果
 * @param corpus    评测时预先写入记忆库的原文；为空时用 {@code input}
 * @param expectedContent 期望说出的记忆内容；为空表示期望拒答
 * @param metadata  附加信息
 */
public record EvalSample(
    EvalDimension dimension, String input, String expected, String corpus,
    String expectedContent, Map<String, String> metadata) {

    /**
     * 构造一个不带附加信息的样本。
     *
     * @param dimension 评测维度
     * @param input     输入
     * @param expected  期望结果
     * @return 样本
     */
    public static EvalSample of(EvalDimension dimension, String input, String expected) {
        return new EvalSample(dimension, input, expected, null, null, Map.of());
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
        return new EvalSample(dimension, input, expected, corpus, corpus, Map.of());
    }

    /**
     * 构造一个"期望拒答"的样本。
     *
     * <p>这类样本<b>不向记忆库写入任何内容</b> ——
     * 记忆库里根本没有对应事实，系统要么编造，要么如实说没有记录。
     *
     * @param dimension 评测维度
     * @param input     输入（问句）
     * @param expected  期望结果
     * @return 样本
     */
    public static EvalSample expectingRefusal(
        EvalDimension dimension, String input, String expected) {
        return new EvalSample(dimension, input, expected, null, null, Map.of());
    }

    /**
     * 返回本条样本的记忆原文。
     *
     * @return 记忆原文；未单独指定时回落为 {@code input}
     */
    public String corpusOrInput() {
        return corpus == null || corpus.isBlank() ? input : corpus;
    }

    /**
     * 返回期望说出的记忆内容。
     *
     * @return 期望内容；为空表示期望拒答
     */
    public String expectedContentOrNull() {
        return expectedContent == null || expectedContent.isBlank() ? null : expectedContent;
    }

    /**
     * 判断本条样本是否期望拒答。
     *
     * @return 期望拒答返回 {@code true}
     */
    public boolean expectsRefusal() {
        return expectedContentOrNull() == null;
    }
}
