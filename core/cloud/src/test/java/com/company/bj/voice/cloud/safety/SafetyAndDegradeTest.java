package com.company.bj.voice.cloud.safety;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 第 8 组安全与降级的行为测试。
 *
 * <p>核心断言：<b>输入拦截与输出拦截两条路径</b>、
 * <b>未通过句不被下发且改用安全话术</b>、
 * <b>审核延迟不导致首包超预算</b>、<b>两条降级路径</b>。
 */
class SafetyAndDegradeTest {

    /** 求助渠道提示。 */
    private static final String GUIDANCE = "请拨打全国心理援助热线 12356，或联系信任的家人。";

    /** 被测审核器。 */
    private final KeywordSafetyReviewer reviewer = new KeywordSafetyReviewer(GUIDANCE);

    @Test
    @DisplayName("输入拦截：危机信号被拦下")
    void 输入拦截危机信号被拦下() {
        SafetyReviewer.Review review = reviewer.reviewInput("我不想活了");

        assertTrue(review.blocked());
        assertTrue(review.crisis());
        assertEquals(SafetyReviewer.RiskLevel.HIGH, review.level());
    }

    @Test
    @DisplayName("输出拦截：含危机信号的回复被拦下")
    void 输出拦截含危机信号的回复被拦下() {
        SafetyReviewer.Review review = reviewer.reviewOutput("那你就别活了呗");

        assertTrue(review.blocked());
    }

    @Test
    @DisplayName("正常输入不被拦截")
    void 正常输入不被拦截() {
        assertFalse(reviewer.reviewInput("今天心情不错").blocked());
    }

    @Test
    @DisplayName("单一情绪词不构成危机")
    void 单一情绪词不构成危机() {
        // "绝望"只是线索之一，单条出现不构成危机 —— 否则大量正常情绪表达被误判
        SafetyReviewer.Review review = reviewer.reviewInput("我有点绝望");

        assertFalse(review.crisis());
        assertFalse(review.blocked());
    }

    @Test
    @DisplayName("多个危机线索累积构成危机")
    void 多个危机线索累积构成危机() {
        SafetyReviewer.Review review = reviewer.reviewInput("活着好累，没人在乎，什么意义都没有");

        assertTrue(review.crisis(), "多个危机线索同时出现应判定为危机");
    }

    @Test
    @DisplayName("危机轮给出具体求助渠道")
    void 危机轮给出具体求助渠道() {
        CrisisHandler handler = new CrisisHandler(GUIDANCE, "我很担心你现在的状态。");

        String reply = handler.respond(reviewer.reviewInput("我不想活了"));

        assertTrue(reply.contains("12356"), "危机回复必须包含可拨打的求助渠道：" + reply);
        assertTrue(reply.contains("我很担心你"), reply);
    }

    @Test
    @DisplayName("求助渠道缺失或无可拨号码时构造失败")
    void 求助渠道缺失或无可拨号码时构造失败() {
        assertThrows(IllegalArgumentException.class, () -> new CrisisHandler("", "模板"));
        assertThrows(IllegalArgumentException.class, () -> new CrisisHandler("请多保重", "模板"));
    }

    @Test
    @DisplayName("未通过句不被下发且改用安全话术")
    void 未通过句不被下发且改用安全话术() {
        StreamingSentenceReviewer streaming =
            new StreamingSentenceReviewer(reviewer, "我换个话题说吧。");

        StreamingSentenceReviewer.SentenceResult result =
            streaming.reviewSentence("你干脆别活了算了");

        assertFalse(result.passed());
        assertEquals("我换个话题说吧。", result.content());
        assertTrue(streaming.approvedSentences().isEmpty(), "未通过的句子不应进入已通过列表");
        assertEquals(1, streaming.blockedCount());
    }

    @Test
    @DisplayName("通过句正常下发")
    void 通过句正常下发() {
        StreamingSentenceReviewer streaming =
            new StreamingSentenceReviewer(reviewer, "我换个话题说吧。");

        StreamingSentenceReviewer.SentenceResult result =
            streaming.reviewSentence("今天天气不错。");

        assertTrue(result.passed());
        assertEquals("今天天气不错。", result.content());
        assertEquals(1, streaming.approvedSentences().size());
    }

    @Test
    @DisplayName("审核延迟不导致首包超预算")
    void 审核延迟不导致首包超预算() {
        long budget = 50;
        FirstPacketBudget packetBudget = new FirstPacketBudget(budget, reviewer);

        // 模拟多句审核
        for (int index = 0; index < 3; index++) {
            packetBudget.reviewAndAccount("今天过得不错。");
        }

        assertFalse(packetBudget.overBudget(),
            "审核耗时 " + packetBudget.reviewMillis() + " 不应超出预算 " + budget);
        assertTrue(packetBudget.remainingBudgetMillis() >= 0);
    }

    @Test
    @DisplayName("审核耗时超出预算时被检出")
    void 审核耗时超出预算时被检出() {
        FirstPacketBudget packetBudget = new FirstPacketBudget(1, reviewer);

        packetBudget.accountReviewMillis(10);

        assertTrue(packetBudget.overBudget());
        assertEquals(0, packetBudget.remainingBudgetMillis());
        assertFalse(packetBudget.canReviewMore(), "预算耗尽后不应再审核");
    }

    @Test
    @DisplayName("降级路径一：TTS 过载切备用供应商")
    void 降级路径一TTS过载切备用供应商() {
        CloudDegradePolicy policy = new CloudDegradePolicy(
            "primary", "backup", "暂时没法说话，先用文字陪你聊。", "我这边有点小状况，稍等一下。", 2);

        policy.recordVoiceFailure("primary");
        assertEquals(CloudDegradePolicy.Level.NORMAL, policy.level(),
            "未达阈值不降级");

        policy.recordVoiceFailure("primary");
        assertEquals(CloudDegradePolicy.Level.BACKUP_VOICE, policy.level());
        assertEquals("backup", policy.currentVoiceProvider());
    }

    @Test
    @DisplayName("降级路径一续：备用也失败则降为纯文本")
    void 降级路径一续备用也失败则降为纯文本() {
        CloudDegradePolicy policy = new CloudDegradePolicy(
            "primary", "backup", "暂时没法说话，先用文字陪你聊。", "我这边有点小状况，稍等一下。", 1);

        policy.recordVoiceFailure("primary");
        policy.recordVoiceFailure("backup");

        assertEquals(CloudDegradePolicy.Level.TEXT_ONLY, policy.level());
        assertEquals("暂时没法说话，先用文字陪你聊。", policy.contentToDeliver("正常的回复"));
    }

    @Test
    @DisplayName("降级路径二：前端异常回落固定话术")
    void 降级路径二前端异常回落固定话术() {
        CloudDegradePolicy policy = new CloudDegradePolicy(
            "primary", "backup", "暂时没法说话，先用文字陪你聊。", "我这边有点小状况，稍等一下。", 2);

        policy.recordFrontendFailure();

        assertEquals(CloudDegradePolicy.Level.FIXED_PHRASE, policy.level());
        assertEquals("我这边有点小状况，稍等一下。", policy.contentToDeliver("正常的回复"));
    }
}
