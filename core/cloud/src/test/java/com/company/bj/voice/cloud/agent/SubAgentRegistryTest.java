package com.company.bj.voice.cloud.agent;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.company.bj.voice.cloud.memory.companion.EmotionClassifier;
import com.company.bj.voice.cloud.memory.companion.UserProfile;
import com.company.bj.voice.cloud.memory.companion.UserProfileStore;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 第 7 组子智能体与裁决器的行为测试。
 *
 * <p>核心断言：<b>新增处理器只需注册即可生效</b>，
 * <b>冲突时采用高优先级输出</b>，<b>人设变更在下一轮生效</b>。
 */
class SubAgentRegistryTest {

    /** 意图标识。 */
    private static final String INTENT_PLAY = "play_music";

    /** 一个只认一个意图的假处理器。 */
    private static final class StubHandler implements SubAgentHandler {
        private final List<String> intents;
        private final int priority;
        private final String output;

        StubHandler(String output, int priority, String... intents) {
            this.output = output;
            this.priority = priority;
            this.intents = List.of(intents);
        }

        @Override
        public SubAgentResult handle(SubAgentRequest request) {
            return SubAgentHandler.SubAgentResult.of(output, request.intent(), "neutral");
        }

        @Override
        public List<String> supportedIntents() {
            return intents;
        }

        @Override
        public int priority() {
            return priority;
        }
    }

    @Test
    @DisplayName("注册后按意图即可路由到处理器")
    void 注册后按意图即可路由到处理器() {
        SubAgentRegistry registry = new SubAgentRegistry();
        registry.register(new StubHandler("好的，播放音乐", 30, INTENT_PLAY));

        assertTrue(registry.find(INTENT_PLAY).isPresent());
        assertTrue(registry.find("不存在的意图").isEmpty());
    }

    @Test
    @DisplayName("新增处理器只需注册即可生效而主流程无需修改")
    void 新增处理器只需注册即可生效而主流程无需修改() {
        SubAgentRegistry registry = new SubAgentRegistry();
        registry.register(new StubHandler("旧处理器的回复", 30, INTENT_PLAY));

        // 模拟"新增一个处理器"：只调 register，主流程代码不变
        registry.register(new StubHandler("新处理器的回复", 25, INTENT_PLAY));

        SubAgentHandler handler = registry.find(INTENT_PLAY).orElseThrow();
        assertEquals("新处理器的回复",
            handler.handle(new SubAgentHandler.SubAgentRequest(INTENT_PLAY, "放歌", "", List.of()))
                .output());
    }

    @Test
    @DisplayName("冲突时采用高优先级输出")
    void 冲突时采用高优先级输出() {
        SubAgentArbitrator arbitrator = new SubAgentArbitrator();

        SubAgentArbitrator.ArbitrationResult result = arbitrator.arbitrate(List.of(
            SubAgentArbitrator.Candidate.of("emotion", 40, 0,
                SubAgentHandler.SubAgentResult.of("我懂你的心情", "emotion", "sadness")),
            SubAgentArbitrator.Candidate.of("safety", 10, 1,
                SubAgentHandler.SubAgentResult.of("这件事我不方便说", "safety", "neutral"))));

        assertTrue(result.hasOutput());
        assertEquals("safety", result.result().intent());
        assertEquals(List.of("emotion"), result.discarded());
    }

    @Test
    @DisplayName("被安全层拦下的结果不会被其他处理器救回")
    void 被安全层拦下的结果不会被其他处理器救回() {
        SubAgentArbitrator arbitrator = new SubAgentArbitrator();

        SubAgentArbitrator.ArbitrationResult result = arbitrator.arbitrate(List.of(
            SubAgentArbitrator.Candidate.of("emotion", 40, 0,
                SubAgentHandler.SubAgentResult.of("我懂你的心情", "emotion", "sadness")),
            SubAgentArbitrator.Candidate.of("safety", 10, 1,
                SubAgentHandler.SubAgentResult.rejected("safety", "触发危机关键词",
                    SubAgentHandler.SafetyLevel.HIGH))));

        assertFalse(result.hasOutput(), "被拦下的结果不应有可下发输出");
        assertTrue(result.result().rejected());
    }

    @Test
    @DisplayName("无候选结果时裁决不崩溃")
    void 无候选结果时裁决不崩溃() {
        SubAgentArbitrator arbitrator = new SubAgentArbitrator();

        SubAgentArbitrator.ArbitrationResult result = arbitrator.arbitrate(List.of());

        assertFalse(result.hasOutput());
        assertEquals("无候选结果", result.reason());
    }

    @Test
    @DisplayName("人设变更在下一轮生效")
    void 人设变更在下一轮生效() {
        PersonaCard.Holder holder = new PersonaCard.Holder(new PersonaCard(
            "v1", "小柔", "你好呀，我是小柔", Map.of("小张", "小张，今天过得怎么样？"),
            "warm", "default-user"));

        PersonaSubAgent agent = new PersonaSubAgent(holder.current(), new UserProfileStore());

        String before = agent.handle(new SubAgentHandler.SubAgentRequest(
            "persona", "你好", "", List.of())).output();
        assertTrue(before.contains("小柔"), before);

        // 热更：换一版人设
        holder.swap(new PersonaCard(
            "v2", "小安", "你好呀，我是小安", Map.of("小张", "小张，今天过得怎么样？"),
            "lively", "default-user"));

        PersonaSubAgent updated = new PersonaSubAgent(holder.current(), new UserProfileStore());
        String after = updated.handle(new SubAgentHandler.SubAgentRequest(
            "persona", "你好", "", List.of())).output();

        assertTrue(after.contains("小安"), after);
        assertFalse(after.contains("小柔"), after);
    }

    @Test
    @DisplayName("共情子智能体按情绪选择话术")
    void 共情子智能体按情绪选择话术() {
        EmpathySubAgent agent = new EmpathySubAgent(
            text -> "sadness",
            Map.of("sadness", "听你这么说，我有点心疼。", "neutral", "嗯，我在。"));

        SubAgentHandler.SubAgentResult result = agent.handle(
            new SubAgentHandler.SubAgentRequest(
                "emotional_support", "我今天很难过", "", List.of()));

        assertEquals("听你这么说，我有点心疼。", result.output());
        assertEquals("sadness", result.emotionTag());
    }

    @Test
    @DisplayName("安全子智能体拦下高危输入")
    void 安全子智能体拦下高危输入() {
        SafetySubAgent agent = new SafetySubAgent(
            text -> new SafetySubAgent.SafetyReviewer.Review(
                SubAgentHandler.SafetyLevel.HIGH, true, "触发危机关键词"),
            "我在这里陪你。");

        SubAgentHandler.SubAgentResult result = agent.handle(
            new SubAgentHandler.SubAgentRequest("safety_review", "我不想活了", "", List.of()));

        assertTrue(result.rejected());
        assertEquals(SubAgentHandler.SafetyLevel.HIGH, result.safetyLevel());
    }

    @Test
    @DisplayName("画像更新子智能体把称呼写入画像")
    void 画像更新子智能体把称呼写入画像() {
        UserProfileStore profileStore = new UserProfileStore();
        ProfileUpdateSubAgent agent = new ProfileUpdateSubAgent(
            profileStore,
            text -> text.contains("叫我小张") ? "小张" : "",
            text -> Set.of());

        agent.handle(new SubAgentHandler.SubAgentRequest(
            "profile_update", "以后叫我小张吧", "", List.of()));

        UserProfile profile = profileStore.load(UserProfileStore.DEFAULT_SCOPE_KEY);
        assertEquals("小张", profile.preferredAddress());
    }

    @Test
    @DisplayName("主控子智能体在无专属话术时回落到兜底话术")
    void 主控子智能体在无专属话术时回落到兜底话术() {
        ControlSubAgent agent = new ControlSubAgent(Map.of(
            ControlSubAgent.INTENT_FALLBACK, "我在呢，想聊点什么？"));

        SubAgentHandler.SubAgentResult result = agent.handle(
            new SubAgentHandler.SubAgentRequest("chitchat", "在吗", "", List.of()));

        assertEquals("我在呢，想聊点什么？", result.output());
    }
}
