package com.company.bj.voice.cloud.memory.companion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * {@link ContextAssembler} 的行为测试。
 *
 * <p>核心断言：<b>各部分按固定顺序装配</b>且<b>总量不超预算</b>。
 */
class ContextAssemblerTest {

    @Test
    @DisplayName("各部分按固定顺序装配")
    void 各部分按固定顺序装配() {
        ContextAssembler assembler = new ContextAssembler();

        ContextAssembler.AssembledContext result = assembler.assemble(
            "你是小柔，温柔耐心",
            "称呼：用户",
            List.of("我妈妈叫李芳"),
            List.of("用户：今天好累"),
            "我今天很难过");

        String context = result.context();
        int personaIndex = context.indexOf("【人设】");
        int profileIndex = context.indexOf("【画像】");
        int memoryIndex = context.indexOf("【记忆】");
        int historyIndex = context.indexOf("【近期对话】");
        int currentIndex = context.indexOf("【当前轮】");

        assertTrue(personaIndex >= 0 && profileIndex > personaIndex,
            "人设应在画像之前");
        assertTrue(memoryIndex > profileIndex, "记忆应在画像之后");
        assertTrue(historyIndex > memoryIndex, "近期对话应在记忆之后");
        assertTrue(currentIndex > historyIndex, "当前轮应在最近期对话之后");
    }

    @Test
    @DisplayName("未超预算时不丢弃任何部分")
    void 未超预算时不丢弃任何部分() {
        ContextAssembler assembler = new ContextAssembler(2000);

        ContextAssembler.AssembledContext result = assembler.assemble(
            "你是小柔", "称呼：用户",
            List.of("我妈妈叫李芳"), List.of("用户：你好"), "今天天气好");

        assertFalse(result.truncated());
        assertTrue(result.droppedSections().isEmpty());
        assertEquals(result.context().length(), result.length());
    }

    @Test
    @DisplayName("超预算时总量不超预算上限")
    void 超预算时总量不超预算上限() {
        int budget = 120;
        ContextAssembler assembler = new ContextAssembler(budget);

        List<String> memories = List.of(
            "记忆一：很长很长很长很长很长很长很长很长很长很长很长很长很长很长很长",
            "记忆二：很长很长很长很长很长很长很长很长很长很长很长很长很长很长很长",
            "记忆三：很长很长很长很长很长很长很长很长很长很长很长很长很长很长很长");

        ContextAssembler.AssembledContext result = assembler.assemble(
            "你是小柔，温柔耐心的陪伴者", "称呼：用户，忌讳：不要提工作",
            memories, List.of("用户：今天好累", "机器人：我在的"), "我今天很难过");

        assertTrue(result.length() <= budget,
            "装配后长度 " + result.length() + " 超过预算 " + budget);
    }

    @Test
    @DisplayName("超预算时优先牺牲长期记忆")
    void 超预算时优先牺牲长期记忆() {
        // 预算必须真的小于"人设+画像+记忆+历史+当前轮"的总长，
        // 否则根本进不了截断分支，测试会变成"没截断"的假阳性。
        String persona = "你是小柔，温柔耐心的陪伴者";
        String profile = "称呼：用户，忌讳：不要提工作";
        String memory = "记忆一：很长很长很长很长很长很长很长很长很长";
        String history = "用户：你好";
        String current = "我今天很难过";

        int total = persona.length() + profile.length() + memory.length()
            + history.length() + current.length();
        int budget = total - memory.length() - 10;

        ContextAssembler assembler = new ContextAssembler(budget);
        ContextAssembler.AssembledContext result = assembler.assemble(
            persona, profile, List.of(memory), List.of(history), current);

        assertTrue(result.truncated(), "输入超预算，必须发生截断");
        assertTrue(result.droppedSections().contains("【记忆】"),
            "应优先丢弃记忆段，实际丢弃：" + result.droppedSections());
        assertTrue(result.context().contains("【当前轮】"), "当前轮必须保留");
        assertTrue(result.length() <= budget,
            "截断后长度 " + result.length() + " 超过预算 " + budget);
    }

    @Test
    @DisplayName("空内容不产生空段落")
    void 空内容不产生空段落() {
        ContextAssembler assembler = new ContextAssembler();

        ContextAssembler.AssembledContext result = assembler.assemble(
            "", "  ", List.of(), List.of(), "你好");

        assertFalse(result.context().contains("【人设】"));
        assertFalse(result.context().contains("【画像】"));
        assertFalse(result.context().contains("【记忆】"));
        assertTrue(result.context().contains("【当前轮】"));
    }

    @Test
    @DisplayName("全部内容为空时返回空上下文")
    void 全部内容为空时返回空上下文() {
        ContextAssembler assembler = new ContextAssembler();

        ContextAssembler.AssembledContext result = assembler.assemble(
            null, null, null, null, "   ");

        assertEquals("", result.context());
        assertEquals(0, result.length());
    }
}
