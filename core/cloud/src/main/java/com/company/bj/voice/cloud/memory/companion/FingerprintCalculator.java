package com.company.bj.voice.cloud.memory.companion;

/**
 * 语义指纹计算器端口。
 *
 * <p>抽成接口是为了让"如何判定两条记忆语义等价"成为一个可替换的策略：
 * 默认实现是 {@link SemanticFingerprint} 的词面归一化，
 * 若将来要引入基于嵌入的语义去重，只需换实现，不必改调用方。
 *
 * <p>这正是架构守则 A3 要求的扩展点形态：接口 + 策略，而不是在调用方
 * 堆 {@code if (使用词面还是语义)} 分支。
 */
@FunctionalInterface
public interface FingerprintCalculator {

    /**
     * 计算一段内容的指纹。
     *
     * @param content 待计算的内容
     * @return 指纹文本；内容为空白时返回空字符串
     */
    String of(String content);

    /**
     * 默认实现：词面归一化指纹。
     *
     * @return 使用 {@link SemanticFingerprint#of(String)} 的计算器
     */
    static FingerprintCalculator lexical() {
        return SemanticFingerprint::of;
    }
}
