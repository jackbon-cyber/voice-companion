package com.company.bj.voice.cloud.embed;

/**
 * 嵌入服务异常。
 *
 * <p>表示嵌入向量的生成过程失败：凭据缺失、网关不可达、响应格式异常或维度不符。
 * 统一为无受检异常，调用方在摄取链路上直接向上抛出即可。
 */
public class EmbeddingException extends RuntimeException {

    /**
     * 以错误消息构造异常。
     *
     * @param message 错误消息
     */
    public EmbeddingException(String message) {
        super(message);
    }

    /**
     * 以错误消息与原始异常构造异常。
     *
     * @param message 错误消息
     * @param cause   原始异常
     */
    public EmbeddingException(String message, Throwable cause) {
        super(message, cause);
    }
}
