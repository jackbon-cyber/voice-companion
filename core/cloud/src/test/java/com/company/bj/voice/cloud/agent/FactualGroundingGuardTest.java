package com.company.bj.voice.cloud.agent;

import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * {@link FactualGroundingGuard} 的行为测试。
 *
 * <p>核心断言：<b>无来源时不编造具体人名地点日期</b>。
 */
class FactualGroundingGuardTest {

    /** 被测守卫。 */
    private final FactualGroundingGuard guard = new FactualGroundingGuard();

    @Test
    @DisplayName("人名有来源时通过")
    void 人名有来源时通过() {
        FactualGroundingGuard.GroundingResult result = guard.verify(
            "你妈妈叫李芳对吧",
            List.of("【记忆】\n我妈妈叫李芳"));

        assertTrue(result.grounded(), result.reason());
    }

    @Test
    @DisplayName("人名无来源时不通过")
    void 人名无来源时不通过() {
        FactualGroundingGuard.GroundingResult result = guard.verify(
            "你妈妈叫李芳对吧",
            List.of("【记忆】\n我昨天去了公园"));

        assertFalse(result.grounded());
        assertTrue(result.ungrounded().contains("李芳"), result.ungrounded().toString());
    }

    @Test
    @DisplayName("地址无来源时不通过")
    void 地址无来源时不通过() {
        FactualGroundingGuard.GroundingResult result = guard.verify(
            "你住在朝阳区望京西园三区",
            List.of("【记忆】\n我住在北京"));

        assertFalse(result.grounded());
        assertTrue(result.ungrounded().size() > 0);
    }

    @Test
    @DisplayName("日期有来源时通过")
    void 日期有来源时通过() {
        FactualGroundingGuard.GroundingResult result = guard.verify(
            "我们约在3月15日见面吧",
            List.of("【记忆】\n我们约在 3 月 15 日见面"));

        assertTrue(result.grounded(), result.reason());
    }

    @Test
    @DisplayName("通用称呼不视为需要来源的事实")
    void 通用称呼不视为需要来源的事实() {
        FactualGroundingGuard.GroundingResult result = guard.verify(
            "我是小柔，我来陪你",
            List.of());

        assertTrue(result.grounded(), result.reason());
    }

    @Test
    @DisplayName("不含事实性表述的回复直接通过")
    void 不含事实性表述的回复直接通过() {
        FactualGroundingGuard.GroundingResult result = guard.verify(
            "听起来你今天挺不容易的",
            List.of());

        assertTrue(result.grounded());
    }

    @Test
    @DisplayName("空回复直接通过")
    void 空回复直接通过() {
        assertTrue(guard.verify("", List.of()).grounded());
    }
}
