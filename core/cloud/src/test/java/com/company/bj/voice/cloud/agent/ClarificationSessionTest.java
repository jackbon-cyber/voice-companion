package com.company.bj.voice.cloud.agent;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 第 7 组澄清会话与输出治理的行为测试。
 *
 * <p>澄清的三条路径：<b>槽位不清空</b>、<b>上限后不再追问</b>、<b>新会话不继承槽位</b>。
 */
class ClarificationSessionTest {

    /** 作用域键。 */
    private static final String SCOPE = "user-1";

    /** 音量槽位。 */
    private static final String SLOT_VOLUME = "volume_level";

    @Test
    @DisplayName("缺槽位时进入追问")
    void 缺槽位时进入追问() {
        ClarificationSession session = new ClarificationSession();

        ClarificationSession.ClarificationOutcome outcome = session.clarify(
            SCOPE, "set_volume", Map.of(), List.of(SLOT_VOLUME), Map.of());

        assertTrue(outcome.needsMore());
        assertEquals(List.of(SLOT_VOLUME), outcome.missingSlots());
        assertEquals(1, outcome.rounds());
    }

    @Test
    @DisplayName("槽位增量合并不清空已有内容")
    void 槽位增量合并不清空已有内容() {
        ClarificationSession session = new ClarificationSession();

        // 第一轮：用户已给出部分槽位（如音乐偏好），音量还缺
        session.clarify(SCOPE, "set_volume", Map.of("music_pref", "轻音乐"),
            List.of(SLOT_VOLUME), Map.of());

        // 第二轮：用户只回答了被问的音量，不重说音乐偏好
        ClarificationSession.ClarificationOutcome outcome = session.clarify(
            SCOPE, "set_volume", Map.of(SLOT_VOLUME, "60"),
            List.of(SLOT_VOLUME), Map.of());

        assertEquals(ClarificationSession.ClarificationStatus.RESOLVED, outcome.status());
        assertEquals("60", outcome.slots().get(SLOT_VOLUME));
        assertEquals("轻音乐", outcome.slots().get("music_pref"),
            "已填的槽位不应在增量合并中被清空");
    }

    @Test
    @DisplayName("超过轮次上限后不再追问并采用候选值")
    void 超过轮次上限后不再追问并采用候选值() {
        ClarificationSession session = new ClarificationSession(2);

        session.clarify(SCOPE, "set_volume", Map.of(), List.of(SLOT_VOLUME), Map.of());
        ClarificationSession.ClarificationOutcome outcome = session.clarify(
            SCOPE, "set_volume", Map.of(), List.of(SLOT_VOLUME),
            Map.of(SLOT_VOLUME, List.of("50", "60")));

        assertEquals(ClarificationSession.ClarificationStatus.ASSUMED, outcome.status());
        assertFalse(outcome.needsMore(), "达到上限后不应再追问");
        assertEquals("50", outcome.slots().get(SLOT_VOLUME));
    }

    @Test
    @DisplayName("新会话不继承槽位")
    void 新会话不继承槽位() {
        ClarificationSession session = new ClarificationSession();
        session.clarify(SCOPE, "set_volume", Map.of(SLOT_VOLUME, "60"),
            List.of(SLOT_VOLUME), Map.of());

        // 换一个作用域键 = 新会话
        ClarificationSession.ClarificationOutcome outcome = session.clarify(
            "user-2", "set_volume", Map.of(), List.of(SLOT_VOLUME), Map.of());

        assertTrue(outcome.needsMore());
        assertFalse(outcome.slots().containsKey(SLOT_VOLUME), "新会话不应继承旧槽位");
    }

    @Test
    @DisplayName("意图改变时清空旧意图的槽位")
    void 意图改变时清空旧意图的槽位() {
        ClarificationSession session = new ClarificationSession();
        session.clarify(SCOPE, "set_volume", Map.of(SLOT_VOLUME, "60"),
            List.of(SLOT_VOLUME), Map.of());

        // 用户改主意说要放歌 —— 不能把"音量=60"带到新意图上
        ClarificationSession.ClarificationOutcome outcome = session.clarify(
            SCOPE, "play_music", Map.of(), List.of(), Map.of());

        assertFalse(outcome.slots().containsKey(SLOT_VOLUME));
    }

    @Test
    @DisplayName("槽位补齐后会话结束")
    void 槽位补齐后会话结束() {
        ClarificationSession session = new ClarificationSession();
        session.clarify(SCOPE, "set_volume", Map.of(), List.of(SLOT_VOLUME), Map.of());

        assertTrue(session.inProgress(SCOPE));

        session.clarify(SCOPE, "set_volume", Map.of(SLOT_VOLUME, "60"),
            List.of(SLOT_VOLUME), Map.of());

        assertFalse(session.inProgress(SCOPE), "槽位补齐后应结束澄清会话");
    }

    @Test
    @DisplayName("重复回复被要求重生成")
    void 重复回复被要求重生成() {
        OutputGovernance governance = new OutputGovernance();
        String reply = "我懂你的难过，陪你聊聊天好不好";

        OutputGovernance.GovernedOutput first = governance.govern(reply, "sadness");
        assertFalse(first.needsRegeneration(), first.reason());

        OutputGovernance.GovernedOutput second = governance.govern(reply, "sadness");
        assertTrue(second.needsRegeneration(), second.reason());
    }

    @Test
    @DisplayName("换词重述也算重复")
    void 换词重述也算重复() {
        OutputGovernance governance = new OutputGovernance();

        governance.govern("我懂你的难过，陪你聊聊天好不好", "sadness");
        OutputGovernance.GovernedOutput result =
            governance.govern("我明白你的难过，陪你聊聊天好不好", "sadness");

        assertTrue(result.needsRegeneration(),
            "仅换一个字的近义重述应被判定为重复，实际相似度 " + result.similarity());
    }

    @Test
    @DisplayName("超出长度上限被截断")
    void 超出长度上限被截断() {
        OutputGovernance governance = new OutputGovernance(10, 0.9, 5);

        OutputGovernance.GovernedOutput result = governance.govern("这是一句非常非常长的话需要被截断掉", "neutral");

        assertEquals(10, result.output().length());
        assertTrue(result.reason().contains("截断"), result.reason());
    }

    @Test
    @DisplayName("情感标签与文本同时产出")
    void 情感标签与文本同时产出() {
        OutputGovernance governance = new OutputGovernance();

        OutputGovernance.GovernedOutput result = governance.govern("我在呢。", "tenderness");

        assertEquals("我在呢。", result.output());
        assertEquals("tenderness", result.emotionTag());
    }
}
