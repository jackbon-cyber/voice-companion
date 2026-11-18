package com.company.bj.voice.cloud.memory.companion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * {@link CompanionMemoryClassifier} 的行为测试。
 *
 * <p>六类内容各覆盖一条路径，另加边界与失败路径 ——
 * 分类错误的代价不对称，因此边界必须有明确断言。
 */
class CompanionMemoryClassifierTest {

    /** 被测分类器。 */
    private final CompanionMemoryClassifier classifier = new CompanionMemoryClassifier();

    @Test
    @DisplayName("关系事实归入长期记忆")
    void 关系事实归入长期记忆() {
        assertEquals(CompanionMemoryCategory.RELATIONSHIP_FACT, classifier.classify("我妈妈叫李芳"));
        assertTrue(classifier.shouldPersistLongTerm("我妈妈叫李芳"));
    }

    @Test
    @DisplayName("稳定偏好归入长期记忆")
    void 稳定偏好归入长期记忆() {
        assertEquals(CompanionMemoryCategory.STABLE_PREFERENCE, classifier.classify("我最喜欢吃红烧肉"));
        assertTrue(classifier.shouldPersistLongTerm("我最喜欢吃红烧肉"));
    }

    @Test
    @DisplayName("时效事件归入长期记忆且可携带过期时间")
    void 时效事件归入长期记忆且可携带过期时间() {
        CompanionMemoryCategory category = classifier.classify("明天我要去体检");
        assertEquals(CompanionMemoryCategory.TIME_SENSITIVE_EVENT, category);
        assertTrue(category.longTerm());
        assertTrue(category.expirable());
    }

    @Test
    @DisplayName("当次情绪归入情景记忆而非长期记忆")
    void 当次情绪归入情景记忆而非长期记忆() {
        CompanionMemoryCategory category = classifier.classify("今天有点难过");
        assertEquals(CompanionMemoryCategory.CURRENT_EMOTION, category);
        assertFalse(category.longTerm());
    }

    @Test
    @DisplayName("一次性设备指令不入长期记忆")
    void 一次性设备指令不入长期记忆() {
        assertEquals(CompanionMemoryCategory.ONE_SHOT_INSTRUCTION, classifier.classify("把音量调到五十"));
        assertFalse(classifier.shouldPersistLongTerm("把音量调到五十"));
        assertTrue(classifier.isOneShotInstruction("把音量调到五十"));
    }

    @Test
    @DisplayName("低信息量寒暄不入长期记忆")
    void 低信息量寒暄不入长期记忆() {
        assertEquals(CompanionMemoryCategory.SMALL_TALK, classifier.classify("你好呀"));
        assertFalse(classifier.shouldPersistLongTerm("你好呀"));
    }

    @Test
    @DisplayName("时效事件的判定优先于情绪——明天很累仍是事件")
    void 时效事件的判定优先于情绪() {
        // 时间词更具体：这句话既含情绪词也含时间词，归到"时效事件"才携带过期时间。
        assertEquals(CompanionMemoryCategory.TIME_SENSITIVE_EVENT, classifier.classify("明天我很累"));
    }

    @Test
    @DisplayName("一次性指令的判定优先于寒暄")
    void 一次性指令的判定优先于寒暄() {
        assertEquals(CompanionMemoryCategory.ONE_SHOT_INSTRUCTION, classifier.classify("播放音乐"));
    }

    @Test
    @DisplayName("空白内容归入寒暄且不抛异常")
    void 空白内容归入寒暄且不抛异常() {
        assertEquals(CompanionMemoryCategory.SMALL_TALK, classifier.classify("   "));
        assertEquals(CompanionMemoryCategory.SMALL_TALK, classifier.classify(null));
    }

    @Test
    @DisplayName("菜名里的'叫'不被误判为关系事实")
    void 菜名里的叫不被误判为关系事实() {
        // 单看"叫"会把这句判成关系事实，但"这"不是关系主体。
        assertEquals(CompanionMemoryCategory.SMALL_TALK, classifier.classify("这道菜叫水煮鱼"));
    }

    @Test
    @DisplayName("疑问句不入长期记忆")
    void 疑问句不入长期记忆() {
        // 疑问句里同样会出现关系词与偏好词。不剔除的话，
        // 用户问"我妈妈叫什么"，"我妈妈叫什么"本身会被当成事实存进长期记忆，
        // 召回时混进问句，机器人会答"你说你想知道你妈妈叫什么" —— 看起来像坏了。
        assertFalse(classifier.shouldPersistLongTerm("我妈妈叫什么"));
        assertFalse(classifier.shouldPersistLongTerm("我喜欢吃什么"));
        assertFalse(classifier.shouldPersistLongTerm("我明天要做什么"));
    }

    @Test
    @DisplayName("含疑问词的陈述句仍可入长期记忆")
    void 含疑问词的陈述句仍可入长期记忆() {
        // "我不知道"含"不"不是疑问；"这些东西我都知道"含"什么"但不是疑问。
        // 疑问判定不能过宽，否则真实事实会被误丢。
        assertTrue(classifier.shouldPersistLongTerm("我妈妈叫李芳，她很喜欢做菜"));
    }
}
