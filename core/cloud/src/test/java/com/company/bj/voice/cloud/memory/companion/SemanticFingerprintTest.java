package com.company.bj.voice.cloud.memory.companion;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 语义指纹与过期策略的行为测试。
 */
class SemanticFingerprintTest {

    /** 基准内容的指纹。 */
    private final String fingerprint = SemanticFingerprint.of("我妈妈叫李芳");

    @Test
    @DisplayName("标点差异不改变指纹")
    void 标点差异不改变指纹() {
        assertTrue(SemanticFingerprint.equivalent("我妈妈叫李芳。", "我妈妈叫李芳"));
        assertTrue(SemanticFingerprint.equivalent("我妈妈叫李芳，", "我妈妈叫李芳"));
    }

    @Test
    @DisplayName("空白差异不改变指纹")
    void 空白差异不改变指纹() {
        assertTrue(SemanticFingerprint.equivalent("我 妈妈 叫 李芳", "我妈妈叫李芳"));
    }

    @Test
    @DisplayName("全角与半角字符不改变指纹")
    void 全角与半角字符不改变指纹() {
        assertTrue(SemanticFingerprint.equivalent("我妈妈叫李芳", "我妈妈叫李芳"));
    }

    @Test
    @DisplayName("中文数字与阿拉伯数字统一")
    void 中文数字与阿拉伯数字统一() {
        assertTrue(SemanticFingerprint.equivalent("我今年二十八岁", "我今年28岁"));
    }

    @Test
    @DisplayName("大小写差异不改变指纹")
    void 大小写差异不改变指纹() {
        assertTrue(SemanticFingerprint.equivalent("I love Coffee", "i love coffee"));
    }

    @Test
    @DisplayName("语义不同的内容指纹不同")
    void 语义不同的内容指纹不同() {
        assertNotEquals(fingerprint, SemanticFingerprint.of("我妈妈叫王芳"));
    }

    @Test
    @DisplayName("空白内容指纹为空且不与任何内容等价")
    void 空白内容指纹为空且不与任何内容等价() {
        assertEquals("", SemanticFingerprint.of("   "));
        assertEquals("", SemanticFingerprint.of(null));
        assertFalse(SemanticFingerprint.equivalent("  ", "我妈妈叫李芳"));
    }

    @Test
    @DisplayName("指纹对同一内容稳定")
    void 指纹对同一内容稳定() {
        assertEquals(SemanticFingerprint.of("我妈妈叫李芳"), SemanticFingerprint.of("我妈妈叫李芳"));
    }
}
