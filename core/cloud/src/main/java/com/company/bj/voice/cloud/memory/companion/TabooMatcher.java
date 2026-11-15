package com.company.bj.voice.cloud.memory.companion;

import java.util.List;
import java.util.Map;

/**
 * 忌讳话题匹配器。
 *
 * <p><b>为什么不能只做子串匹配</b>：忌讳记的是"前任"，
 * 用户说"我前男友"时子串匹配<b>不命中</b> —— 而这恰恰是最需要拦截的表达。
 * 换一种说法就能绕过，那这个维度形同虚设。
 *
 * <p><b>本匹配器用两层判定</b>：
 * <ol>
 *   <li><b>字面命中</b>：文本包含忌讳词本身；</li>
 *   <li><b>变体命中</b>：文本命中忌讳词的<b>已知变体</b>
 *       （如"前任"的变体含"前男友""前女友""前夫""前妻"）。</li>
 * </ol>
 *
 * <p><b>变体表是显式维护的，不是自动推导的</b>：自动推导（替换字、拼音近似）
 * 会产生大量误伤 —— 把"前同事"判成"前任"的代价是机器人无缘无故回避
 * 用户很正常的话题，比漏拦一次更伤陪伴体验。
 * 显式变体表的代价是要人工维护，但每次漏拦都可以直接补一行。
 */
public class TabooMatcher {

    /** 忌讳词的变体表。键为忌讳词，值为等价说法。 */
    private static final Map<String, List<String>> VARIANTS = Map.of(
        "前任", List.of("前男友", "前女友", "前夫", "前妻", "前伴侣", "以前的男朋友", "以前的女朋友"),
        "离婚", List.of("离过婚", "婚姻破裂"),
        "失业", List.of("丢了工作", "被裁员", "被辞退"));

    /**
     * 判断文本是否命中某个忌讳。
     *
     * @param topic 话题文本
     * @param taboo  忌讳词
     * @return 命中返回 {@code true}
     */
    public boolean matches(String topic, String taboo) {
        if (topic == null || topic.isBlank() || taboo == null || taboo.isBlank()) {
            return false;
        }
        if (topic.contains(taboo)) {
            return true;
        }
        for (String variant : VARIANTS.getOrDefault(taboo, List.of())) {
            if (topic.contains(variant)) {
                return true;
            }
        }
        return false;
    }

    /**
     * 找出文本命中的全部忌讳。
     *
     * @param topic  话题文本
     * @param taboos 忌讳词集合
     * @return 命中的忌讳词列表
     */
    public List<String> matchedTaboos(String topic, Iterable<String> taboos) {
        java.util.List<String> hits = new java.util.ArrayList<>();
        for (String taboo : taboos) {
            if (matches(topic, taboo)) {
                hits.add(taboo);
            }
        }
        return hits;
    }
}
