package com.company.bj.voice.cloud.auth;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

/**
 * 上行通道鉴权器。
 *
 * <p><b>为什么鉴权在握手阶段而不是消息级</b>：端侧建立 WebSocket 连接时
 * 携带凭据，云端在**握手阶段**判定。这样未授权的客户端根本进不来，
 * 不会占用处理单元的内存，也不会消耗协议解析与校验的开销。
 * 若放到消息级，未授权客户端可以先建立连接、再持续发垃圾消息，
 * 拒绝的成本反而更高。
 *
 * <p><b>为什么用常量时间比较</b>：逐字符比较会在第一个不同字节处返回，
 * 攻击者可以通过响应时间差逐位试探凭据。用 {@link MessageDigest#isEqual}
 * 做常量时间比较，消除这个侧信道。
 *
 * <p><b>为什么失败时不区分"缺失"与"错误"</b>：区分会让攻击者知道
 * "凭据格式对不对"，多给了一条信息但没多给能力。统一报"凭据缺失或无效"。
 */
public class TokenAuthenticator {

    /** 鉴权失败时统一使用的错误信息。 */
    public static final String INVALID_CREDENTIAL_MESSAGE = "凭据缺失或无效";

    /** 允许的凭据。为空表示未启用鉴权。 */
    private final String expectedToken;

    /**
     * 构造鉴权器。
     *
     * @param expectedToken 期望的凭据；为 null 或空串表示**未启用鉴权**
     */
    public TokenAuthenticator(String expectedToken) {
        this.expectedToken = expectedToken == null ? "" : expectedToken;
    }

    /**
     * 查询鉴权是否已启用。
     *
     * <p>未启用时所有连接都会被放行 —— 这是**开发期**的形态。
     * 生产部署必须配置凭据，否则上行通道对任何人都开放。
     *
     * @return 已启用时为 true
     */
    public boolean isEnabled() {
        return !expectedToken.isEmpty();
    }

    /**
     * 校验凭据。
     *
     * @param presentedToken 客户端携带的凭据；可为 null
     * @throws AuthenticationException 鉴权未启用以外的任何失败情形
     */
    public void authenticate(String presentedToken) {
        if (!isEnabled()) {
            // 未启用鉴权：开发期的默认形态，放行但不静默 ——
            // 生产环境忘记配凭据是最危险的失误，必须在日志里显式告警。
            return;
        }
        if (presentedToken == null || presentedToken.isEmpty()) {
            throw new AuthenticationException(INVALID_CREDENTIAL_MESSAGE);
        }
        if (!constantTimeEquals(expectedToken, presentedToken)) {
            throw new AuthenticationException(INVALID_CREDENTIAL_MESSAGE);
        }
    }

    /**
     * 常量时间比较两个字符串。
     *
     * @param expected 期望值
     * @param actual 实际值
     * @return 相等时为 true
     */
    private boolean constantTimeEquals(String expected, String actual) {
        return MessageDigest.isEqual(
                expected.getBytes(StandardCharsets.UTF_8),
                actual.getBytes(StandardCharsets.UTF_8));
    }
}
