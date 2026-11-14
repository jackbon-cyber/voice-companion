package com.company.bj.voice.cloud.memory.companion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.List;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * {@link MemoryConflictResolver} 的行为测试。
 *
 * <p>覆盖 spec 要求的全部三种情形，另加并列保留的消歧标记断言。
 */
class MemoryConflictResolverTest {

    /** 被测消解器。 */
    private final MemoryConflictResolver resolver = new MemoryConflictResolver();

    /**
     * 构造一条测试用记忆。
     *
     * @param id         标识
     * @param content    正文
     * @param confidence 置信度
     * @param createdAt  创建时间戳
     * @return 记忆条目
     */
    private CompanionMemory memory(String id, String content, double confidence, long createdAt) {
        return new CompanionMemory(id, content, 1.0, createdAt, 0L, confidence,
            CompanionMemoryCategory.RELATIONSHIP_FACT, id, "default", "default", false);
    }

    @Test
    @DisplayName("置信度不同取高者")
    void 置信度不同取高者() {
        CompanionMemory high = memory("a", "我妈妈叫李芳", 0.9, 1000L);
        CompanionMemory low = memory("b", "我妈妈叫王芳", 0.5, 2000L);

        MemoryConflictResolver.ConflictResolution result = resolver.resolve(high, low);

        assertEquals(MemoryConflictResolver.ResolutionReason.HIGHER_CONFIDENCE, result.reason());
        assertEquals(List.of(high), result.winners());
        assertEquals(low, result.loser());
    }

    @Test
    @DisplayName("置信度接近取较新者")
    void 置信度接近取较新者() {
        CompanionMemory older = memory("a", "我妈妈叫李芳", 0.80, 1000L);
        CompanionMemory newer = memory("b", "我妈妈叫王芳", 0.82, 2000L);

        MemoryConflictResolver.ConflictResolution result = resolver.resolve(older, newer);

        assertEquals(MemoryConflictResolver.ResolutionReason.NEWER_TIMESTAMP, result.reason());
        assertEquals(List.of(newer), result.winners());
        assertEquals(older, result.loser());
    }

    @Test
    @DisplayName("置信度与时间均无法区分时并列保留")
    void 置信度与时间均无法区分时并列保留() {
        CompanionMemory left = memory("a", "我妈妈叫李芳", 0.80, 1000L);
        CompanionMemory right = memory("b", "我妈妈叫李芳", 0.80, 1000L);

        MemoryConflictResolver.ConflictResolution result = resolver.resolve(left, right);

        assertEquals(MemoryConflictResolver.ResolutionReason.KEEP_BOTH, result.reason());
        assertEquals(2, result.winners().size());
        assertNull(result.loser());
        assertTrue(result.requiresDisambiguation());
    }

    @Test
    @DisplayName("并列保留时不被标记为消歧的场合为假")
    void 并列保留时不被标记为消歧的场合为假() {
        CompanionMemory high = memory("a", "内容", 0.9, 1000L);
        CompanionMemory low = memory("b", "内容", 0.4, 1000L);

        assertFalse(resolver.resolve(high, low).requiresDisambiguation());
    }

    @Test
    @DisplayName("空候选抛出异常而不是静默返回")
    void 空候选抛出异常而不是静默返回() {
        CompanionMemory valid = memory("a", "内容", 0.8, 1000L);
        try {
            resolver.resolve(valid, null);
            throw new AssertionError("空候选应当抛出 IllegalArgumentException");
        } catch (IllegalArgumentException expected) {
            assertTrue(expected.getMessage().contains("must not be null"));
        }
    }
}
