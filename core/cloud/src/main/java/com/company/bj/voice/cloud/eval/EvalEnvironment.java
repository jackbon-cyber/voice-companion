package com.company.bj.voice.cloud.eval;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 评测环境信息。
 *
 * <p><b>记录什么</b>：评测所依赖的外部组件的版本与配置 ——
 * ChromaDB 版本、嵌入模型名与维度、JDK 版本等。
 *
 * <p><b>为什么不记录时间戳</b>：评测报告会被提交或存进版本库供人比对。
 * 若报告里带生成时间，两次运行的 diff 就必然出现一行无关的噪声，
 * 真实指标的变化会被淹没 —— 而"两次运行的差异只反映真实变化"
 * 恰恰是版本控制友好性的全部意义。
 *
 * <p><b>因此本类刻意不接受时间戳</b>：构造时能传入的只有稳定的组件标识。
 * 想加时间戳的人必须先改这个类，从而被迫面对"这行噪声值不值得"这个问题。
 *
 * <p><b>输出顺序稳定</b>：按插入顺序（{@link LinkedHashMap}）渲染，
 * 避免 HashMap 的无序导致同一份环境信息渲染出不同的文本。
 */
public final class EvalEnvironment {

    /** 环境条目。键为组件名，值为版本或配置标识。 */
    private final Map<String, String> entries;

    /**
     * 构造环境信息。
     *
     * @param entries 环境条目；为 {@code null} 时视为空
     */
    public EvalEnvironment(Map<String, String> entries) {
        this.entries = entries == null
            ? Map.of()
            : new LinkedHashMap<>(entries);
    }

    /**
     * 返回环境条目的键，按插入顺序。
     *
     * @return 键列表
     */
    public List<String> keys() {
        return new ArrayList<>(entries.keySet());
    }

    /**
     * 读取某个环境条目的值。
     *
     * @param key 组件名
     * @return 条目值；不存在时返回空串
     */
    public String value(String key) {
        String value = entries.get(key);
        return value == null ? "" : value;
    }

    /**
     * 渲染为 Markdown 的列表项。
     *
     * <p>每个条目独占一行，便于人读，也便于 diff 逐行比对。
     *
     * @return Markdown 文本；无条目时返回空串
     */
    public String toMarkdown() {
        StringBuilder builder = new StringBuilder();
        for (Map.Entry<String, String> entry : entries.entrySet()) {
            builder.append("- ").append(entry.getKey()).append(": ").append(entry.getValue())
                .append("\n");
        }
        return builder.toString();
    }
}
