package com.company.bj.voice.cloud.auth;

/**
 * 鉴权失败异常。
 *
 * <p>继承 {@link RuntimeException}：鉴权失败是运行期链路问题，不是调用方用错了 API。
 *
 * <p>异常消息里**不得包含凭据本身** —— 异常消息会进日志，
 * 而日志会被截图发到群里或传进日志采集系统。
 */
public class AuthenticationException extends RuntimeException {

    /**
     * 以给定消息构造异常。
     *
     * @param message 异常消息
     */
    public AuthenticationException(String message) {
        super(message);
    }
}
