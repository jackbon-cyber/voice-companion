package com.company.bj.voice.cloud.memory.companion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.time.Duration;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * {@link ExpiryPolicy} 的行为测试。
 */
class ExpiryPolicyTest {

    /** 被测策略。 */
    private final ExpiryPolicy policy = new ExpiryPolicy();

    /** 固定基准时刻，避免测试依赖真实时钟。 */
    private static final long NOW = 1_700_000_000_000L;

    @Test
    @DisplayName("过期时间戳为零表示永不过期")
    void 过期时间戳为零表示永不过期() {
        assertFalse(policy.isExpired(0L, NOW));
        assertFalse(policy.isExpired(0L, NOW + Duration.ofDays(365).toMillis()));
    }

    @Test
    @DisplayName("到达过期时间即判为过期")
    void 到达过期时间即判为过期() {
        long expiresAt = NOW + 1000L;
        assertFalse(policy.isExpired(expiresAt, expiresAt - 1));
        assertTrue(policy.isExpired(expiresAt, expiresAt));
        assertTrue(policy.isExpired(expiresAt, expiresAt + 1));
    }

    @Test
    @DisplayName("明天的内容估算为一天后过期")
    void 明天的内容估算为一天后过期() {
        long expiry = policy.estimateExpiry("明天我要去体检", NOW);
        assertEquals(NOW + Duration.ofDays(1).toMillis(), expiry);
    }

    @Test
    @DisplayName("下周的内容估算为一周后过期")
    void 下周的内容估算为一周后过期() {
        long expiry = policy.estimateExpiry("下周我要出差", NOW);
        assertEquals(NOW + Duration.ofDays(7).toMillis(), expiry);
    }

    @Test
    @DisplayName("不含时效线索的内容永不过期")
    void 不含时效线索的内容永不过期() {
        assertEquals(0L, policy.estimateExpiry("我妈妈叫李芳", NOW));
        assertEquals(0L, policy.estimateExpiry("", NOW));
        assertEquals(0L, policy.estimateExpiry(null, NOW));
    }

    @Test
    @DisplayName("未指明时长的事件走默认有效期")
    void 未指明时长的事件走默认有效期() {
        // 已被判定为时效事件但没说具体时间时，用保守的默认有效期，
        // 而不是让它永不过期 —— 那会让过期机制形同虚设。
        assertEquals(NOW + Duration.ofDays(ExpiryPolicy.DEFAULT_VALIDITY_DAYS).toMillis(),
            policy.defaultExpiry(NOW));
    }

    @Test
    @DisplayName("大后天不被误算成后天")
    void 大后天不被误算成后天() {
        assertEquals(3, policy.extractValidityDays("大后天我要出差"));
    }
}
