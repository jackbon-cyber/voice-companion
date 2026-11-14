package com.company.bj.voice.cloud.chroma;

/**
 * Chroma 交互过程中抛出的运行时异常。
 *
 * <p>用于统一表达三类失败：服务端返回非 2xx、连接被拒绝、超时或响应体无法解析。
 * 调用方无需区分这些底层差异即可向上层传播"Chroma 不可用"的语义。
 */
public class ChromaException extends RuntimeException {

    private static final long serialVersionUID = 1L;

    /**
     * 以错误消息构造异常。
     *
     * @param message 错误描述
     */
    public ChromaException(String message) {
        super(message);
    }

    /**
     * 以错误消息与原始异常构造异常。
     *
     * @param message 错误描述
     * @param cause   原始异常
     */
    public ChromaException(String message, Throwable cause) {
        super(message, cause);
    }
}
