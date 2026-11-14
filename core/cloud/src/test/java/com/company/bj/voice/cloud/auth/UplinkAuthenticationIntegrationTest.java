package com.company.bj.voice.cloud.auth;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.net.URI;
import java.util.concurrent.CopyOnWriteArrayList;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.context.TestPropertySource;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketHttpHeaders;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.client.standard.StandardWebSocketClient;
import org.springframework.web.socket.handler.TextWebSocketHandler;

/**
 * 上行通道握手鉴权的端到端测试。
 *
 * <p>测的是**真实握手路径**而不是鉴权器本身 ——
 * 鉴权器单测通过但拦截器没接上，握手仍然会放行。
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@TestPropertySource(properties = "voice.uplink.token=test-secret-token")
class UplinkAuthenticationIntegrationTest {

    /** 实际监听的端口。 */
    @LocalServerPort
    private int port;

    /** 握手成功时收到的消息。 */
    private final CopyOnWriteArrayList<String> received = new CopyOnWriteArrayList<>();

    /**
     * 构造上行地址。
     *
     * @param token 凭据；为空表示不携带
     * @return 上行地址
     */
    private URI uplinkUri(String token) {
        String base = "ws://127.0.0.1:" + port + "/voice/uplink";
        return URI.create(token == null ? base : base + "?token=" + token);
    }

    /**
     * 用给定凭据尝试建立连接。
     *
     * @param token 凭据；为空表示不携带
     * @return 建立成功时返回会话
     */
    private WebSocketSession connect(String token) throws Exception {
        StandardWebSocketClient client = new StandardWebSocketClient();
        return client.execute(
                        new TextWebSocketHandler() {
                            @Override
                            protected void handleTextMessage(WebSocketSession session, TextMessage message) {
                                received.add(message.getPayload());
                            }
                        },
                        new WebSocketHttpHeaders(),
                        uplinkUri(token))
                .get();
    }

    @Test
    void 有效凭据可以建立连接() throws Exception {
        WebSocketSession session = connect("test-secret-token");

        assertThat(session.isOpen()).isTrue();
        session.close(CloseStatus.NORMAL);
    }

    @Test
    void 无效凭据被拒绝建立连接() {
        assertThatThrownBy(() -> connect("wrong-token")).isNotNull();
    }

    @Test
    void 缺失凭据被拒绝建立连接() {
        assertThatThrownBy(() -> connect(null)).isNotNull();
    }

    @Test
    void 鉴权失败时不会收到任何消息() {
        assertThatThrownBy(() -> connect("wrong-token")).isNotNull();

        assertThat(received).isEmpty();
    }

    @Test
    void Bearer请求头也可以携带凭据() throws Exception {
        StandardWebSocketClient client = new StandardWebSocketClient();
        WebSocketHttpHeaders headers = new WebSocketHttpHeaders();
        headers.add("Authorization", "Bearer test-secret-token");

        WebSocketSession session =
                client.execute(new TextWebSocketHandler() {}, headers, uplinkUri(null)).get();

        assertThat(session.isOpen()).isTrue();
        session.close(CloseStatus.NORMAL);
    }

    @Test
    void 错误的前缀不被接受() {
        StandardWebSocketClient client = new StandardWebSocketClient();
        WebSocketHttpHeaders headers = new WebSocketHttpHeaders();
        headers.add("Authorization", "Basic test-secret-token");

        assertThatThrownBy(
                        () ->
                                client.execute(
                                                new TextWebSocketHandler() {}, headers, uplinkUri(null))
                                        .get())
                .isNotNull();
    }

    @Test
    void 凭据不出现在握手异常信息中() {
        String message = null;
        try {
            connect("leaked-value");
        } catch (Exception error) {
            message = error.getMessage();
        }

        assertThat(message).isNotNull();
        assertThat(message).doesNotContain("leaked-value");
    }
}
