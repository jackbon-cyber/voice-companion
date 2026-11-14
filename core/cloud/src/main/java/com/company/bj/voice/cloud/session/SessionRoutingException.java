package com.company.bj.voice.cloud.session;

/**
 * 会话路由异常。
 *
 * <p>继承 {@link RuntimeException}：路由失败是运行期链路问题，不是调用方用错了 API。
 */
public class SessionRoutingException extends RuntimeException {

    /**
     * 以给定消息构造异常。
     *
     * @param message 异常消息
     */
    public SessionRoutingException(String message) {
        super(message);
    }

    /**
     * 以给定消息与根因构造异常。
     *
     * @param message 异常消息
     * @param cause 根因
     */
    public SessionRoutingException(String message, Throwable cause) {
        super(message, cause);
    }
}
