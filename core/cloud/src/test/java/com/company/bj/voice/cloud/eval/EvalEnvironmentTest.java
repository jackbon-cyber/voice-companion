package com.company.bj.voice.cloud.eval;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * {@link EvalEnvironment} 的行为测试。
 *
 * <p>核心断言：<b>环境信息不含时间戳等易变内容</b>，
 * 因此两次运行的报告 diff 只反映真实指标变化。
 */
class EvalEnvironmentTest {

    /**
     * 构造一份环境信息。
     *
     * @return 环境信息
     */
    private static EvalEnvironment sample() {
        Map<String, String> entries = new LinkedHashMap<>(4);
        entries.put("chroma", "1.0.0");
        entries.put("embedding", "local-bge-small-zh/512");
        entries.put("jdk", "21.0.13");
        return new EvalEnvironment(entries);
    }

    @Test
    @DisplayName("环境信息按插入顺序稳定输出")
    void 环境信息按插入顺序稳定输出() {
        EvalEnvironment environment = sample();

        assertEquals(List.of("chroma", "embedding", "jdk"), environment.keys());
        assertEquals("1.0.0", environment.value("chroma"));
    }

    @Test
    @DisplayName("未知键返回空串而不是抛异常")
    void 未知键返回空串而不是抛异常() {
        EvalEnvironment environment = sample();

        assertEquals("", environment.value("不存在的键"));
    }

    @Test
    @DisplayName("环境信息不含时间戳，保证两次运行报告可比")
    void 环境信息不含时间戳保证两次运行报告可比() {
        // 时间戳是"每次都不一样"的字段：报告里一旦带上它，
        // 两次运行的 diff 就必然出现噪声行，真实指标的变化会被淹没。
        // 这里把"不得包含时间戳"钉成测试，防止有人日后顺手加回去。
        EvalEnvironment environment = sample();

        for (String key : environment.keys()) {
            String lower = key.toLowerCase(java.util.Locale.ROOT);
            assertFalse(lower.contains("time") || lower.contains("date") || lower.contains("stamp"),
                "环境信息不应包含时间维度字段：" + key);
        }

        String rendered = environment.toMarkdown();
        assertFalse(rendered.contains("20"), "环境信息渲染不得包含形如年份的数字：" + rendered);
    }

    @Test
    @DisplayName("空环境信息渲染为空串")
    void 空环境信息渲染为空串() {
        EvalEnvironment empty = new EvalEnvironment(Map.of());

        assertEquals("", empty.toMarkdown());
        assertTrue(empty.keys().isEmpty());
    }

    @Test
    @DisplayName("渲染结果为每行一条的键值对")
    void 渲染结果为每行一条的键值对() {
        String rendered = sample().toMarkdown();

        assertTrue(rendered.contains("chroma"), rendered);
        assertTrue(rendered.contains("1.0.0"), rendered);
        assertTrue(rendered.contains("\n"), "每个键值对应独占一行");
    }
}
