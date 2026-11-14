package com.company.bj.voice.cloud.auth;

import java.util.List;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.server.ServerHttpRequest;
import org.springframework.http.server.ServerHttpResponse;
import org.springframework.http.server.ServletServerHttpRequest;
import org.springframework.web.socket.WebSocketHandler;
import org.springframework.web.socket.server.HandshakeInterceptor;

/**
 * 上行通道握手鉴权拦截器。
 *
 * <p>在 HTTP 升级为 WebSocket 之前判定凭据。未通过则直接拒绝握手 ——
 * 连接根本不会建立，端侧收到的是握手失败而不是"连上了但没反应"。
 *
 * <p><b>凭据从哪来</b>：优先取查询参数 {@code token}，其次取请求头
 * {@code Authorization: Bearer <token>}。查询参数是 WebSocket 客户端
 * （浏览器与 Python 的 {@code websockets} 库）唯一方便的传参方式 ——
 * 浏览器端的 WebSocket API 不能自定义请求头。
 *
 * <p><b>为什么不在 URL 里放长期凭据</b>：URL 会被记录在访问日志、
 * 代理日志与浏览器历史里。短期令牌 + 定期轮换是标准做法；
 * 本阶段用静态令牌是为了把鉴权链路先跑通，令牌轮换属后续阶段。
 */
public class HandshakeAuthInterceptor implements HandshakeInterceptor {

    /** 日志器。 */
    private static final Logger LOGGER = LoggerFactory.getLogger(HandshakeAuthInterceptor.class);

    /** 查询参数中的凭据名。 */
    public static final String TOKEN_PARAMETER = "token";

    /** 承载 Bearer 凭据的请求头。 */
    public static final String AUTHORIZATION_HEADER = "Authorization";

    /** Bearer 前缀。 */
    private static final String BEARER_PREFIX = "Bearer ";

    /** 鉴权器。 */
    private final TokenAuthenticator authenticator;

    /**
     * 构造拦截器。
     *
     * @param authenticator 鉴权器
     */
    public HandshakeAuthInterceptor(TokenAuthenticator authenticator) {
        this.authenticator = authenticator;
    }

    @Override
    public boolean beforeHandshake(
            ServerHttpRequest request,
            ServerHttpResponse response,
            WebSocketHandler wsHandler,
            Map<String, Object> attributes) {
        if (!authenticator.isEnabled()) {
            LOGGER.warn("上行通道未配置凭据，任何客户端都能接入 —— 生产部署必须配置");
            return true;
        }

        String presented = extractToken(request);
        try {
            authenticator.authenticate(presented);
        } catch (AuthenticationException error) {
            // 消息里不含凭据本身，避免凭据进日志。
            LOGGER.warn("上行通道鉴权失败，已拒绝握手：{}", error.getMessage());
            setUnauthorizedStatus(response);
            return false;
        }
        return true;
    }

    /**
     * 把响应状态设为 401。
     *
     * <p>握手拦截器返回 false 时，Spring 的默认响应码是 <b>200</b> ——
     * 客户端看到的是"服务器返回了 200，但没升级成 WebSocket"，
     * 报出来是 {@code InvalidStatus: HTTP 200}，完全看不出是鉴权问题。
     * 显式设成 401 才能让端侧识别出"这是凭据问题，去改配置"。
     *
     * @param response 服务端响应
     */
    private void setUnauthorizedStatus(ServerHttpResponse response) {
        response.setStatusCode(HttpStatus.UNAUTHORIZED);
    }

    @Override
    public void afterHandshake(
            ServerHttpRequest request,
            ServerHttpResponse response,
            WebSocketHandler wsHandler,
            Exception exception) {
        // 握手后无需处理。
    }
    /**
     * 从请求中取出凭据。
     *
     * @param request 服务端请求
     * @return 凭据；取不到时返回 null
     */
    private String extractToken(ServerHttpRequest request) {
        String fromParameter = extractParameter(request);
        if (fromParameter != null && !fromParameter.isEmpty()) {
            return fromParameter;
        }
        return extractBearerHeader(request);
    }

    /**
     * 从查询参数取凭据。
     *
     * @param request 服务端请求
     * @return 凭据；取不到时返回 null
     */
    private String extractParameter(ServerHttpRequest request) {
        if (!(request instanceof ServletServerHttpRequest servletRequest)) {
            return null;
        }
        String value = servletRequest.getServletRequest().getParameter(TOKEN_PARAMETER);
        return value == null || value.isEmpty() ? null : value;
    }

    /**
     * 从 Authorization 头取 Bearer 凭据。
     *
     * @param request 服务端请求
     * @return 凭据；取不到时返回 null
     */
    private String extractBearerHeader(ServerHttpRequest request) {
        List<String> headers = request.getHeaders().get(AUTHORIZATION_HEADER);
        if (headers == null || headers.isEmpty()) {
            return null;
        }
        String header = headers.get(0);
        if (header == null || !header.startsWith(BEARER_PREFIX)) {
            return null;
        }
        String token = header.substring(BEARER_PREFIX.length()).trim();
        return token.isEmpty() ? null : token;
    }
}
