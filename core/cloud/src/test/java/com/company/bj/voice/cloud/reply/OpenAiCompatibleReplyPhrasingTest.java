package com.company.bj.voice.cloud.reply;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.company.bj.voice.cloud.config.LlmProperties;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import java.io.IOException;
import java.net.InetSocketAddress;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * {@link OpenAiCompatibleReplyPhrasing} 的测试。
 *
 * <p>用真实的本地 HTTP 服务模拟 OpenAI 兼容接口，
 * 而不是 mock {@code HttpClient} —— 协议细节（请求体形状、响应解析）
 * 恰恰是最容易出错的地方，mock 掉就测不到。
 */
class OpenAiCompatibleReplyPhrasingTest {

    /** 模拟网关返回的回复正文。 */
    private static final String GENERATED_TEXT = "记得呀，你妈妈叫李芳。";

    /** 本地模拟服务。 */
    private HttpServer server;

    /** 模拟服务收到的最后一个请求体。 */
    private volatile String lastRequestBody;

    /** 模拟服务收到的最后一个 Authorization 头。 */
    private volatile String lastAuthorization;

    /**
     * 启动本地模拟网关。
     *
     * @throws IOException 端口绑定失败时抛出
     */
    @BeforeEach
    void 启动模拟网关() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/chat/completions", exchange -> {
            lastRequestBody = new String(exchange.getRequestBody().readAllBytes());
            lastAuthorization = exchange.getRequestHeaders().getFirst("Authorization");
            byte[] response = ("{\"choices\":[{\"message\":{\"content\":\"" + GENERATED_TEXT + "\"}}]}")
                .getBytes("UTF-8");
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, response.length);
            exchange.getResponseBody().write(response);
            exchange.close();
        });
        server.start();
    }

    /**
     * 停止本地模拟网关。
     */
    @AfterEach
    void 停止模拟网关() {
        if (server != null) {
            server.stop(0);
        }
    }

    /**
     * 构造指向本地模拟网关的配置。
     *
     * @param apiKey 凭据
     * @return 配置
     */
    private LlmProperties 指向模拟网关(String apiKey) {
        LlmProperties props = new LlmProperties();
        props.setBaseUrl("http://127.0.0.1:" + server.getAddress().getPort());
        props.setApiKey(apiKey);
        props.setModel("test-model");
        props.setTimeoutSeconds(5);
        return props;
    }

    /**
     * 构造生成器。
     *
     * @param apiKey 凭据
     * @return 生成器
     */
    private OpenAiCompatibleReplyPhrasing 生成器(String apiKey) {
        return new OpenAiCompatibleReplyPhrasing(
                指向模拟网关(apiKey), java.net.http.HttpClient.newHttpClient(), new ObjectMapper());
    }

    @Test
    @DisplayName("正常路径：返回生成的措辞")
    void 正常路径返回生成的措辞() {
        OpenAiCompatibleReplyPhrasing phrasing = 生成器("test-key");

        String result = phrasing.phrase("我妈妈叫李芳");

        assertEquals(GENERATED_TEXT, result, "应返回网关生成的文本");
    }

    @Test
    @DisplayName("请求体符合 OpenAI 兼容格式")
    void 请求体符合OpenAI兼容格式() {
        OpenAiCompatibleReplyPhrasing phrasing = 生成器("test-key");

        phrasing.phrase("我妈妈叫李芳");

        assertTrue(lastRequestBody.contains("\"model\":\"test-model\""),
                "请求体应包含模型名");
        assertTrue(lastRequestBody.contains("\"messages\""), "请求体应包含消息列表");
        assertTrue(lastRequestBody.contains("我妈妈叫李芳"), "请求体应包含记忆内容");
        assertTrue(lastRequestBody.contains("\"role\":\"system\""), "请求体应包含系统提示");
    }

    @Test
    @DisplayName("凭据以 Bearer 形式发送")
    void 凭据以Bearer形式发送() {
        OpenAiCompatibleReplyPhrasing phrasing = 生成器("secret-key");

        phrasing.phrase("我妈妈叫李芳");

        assertEquals("Bearer secret-key", lastAuthorization, "授权头格式不正确");
    }

    @Test
    @DisplayName("失败路径：网关返回非 2xx 时返回空串")
    void 网关返回非2xx时返回空串() throws IOException {
        HttpServer failing = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        failing.createContext("/chat/completions", exchange -> {
            byte[] response = "{\"error\":\"boom\"}".getBytes("UTF-8");
            exchange.sendResponseHeaders(500, response.length);
            exchange.getResponseBody().write(response);
            exchange.close();
        });
        failing.start();
        try {
            LlmProperties props = new LlmProperties();
            props.setBaseUrl("http://127.0.0.1:" + failing.getAddress().getPort());
            props.setApiKey("k");
            props.setTimeoutSeconds(5);
            OpenAiCompatibleReplyPhrasing phrasing = new OpenAiCompatibleReplyPhrasing(
                    props, java.net.http.HttpClient.newHttpClient(), new ObjectMapper());

            String result = phrasing.phrase("我妈妈叫李芳");

            assertEquals("", result, "网关失败时应返回空串让调用方退回模板");
        } finally {
            failing.stop(0);
        }
    }

    @Test
    @DisplayName("失败路径：网关不可达时返回空串")
    void 网关不可达时返回空串() {
        // 指向一个必定无监听的端口。
        LlmProperties props = new LlmProperties();
        props.setBaseUrl("http://127.0.0.1:1");
        props.setApiKey("k");
        props.setTimeoutSeconds(2);
        OpenAiCompatibleReplyPhrasing phrasing = new OpenAiCompatibleReplyPhrasing(
                props, java.net.http.HttpClient.newHttpClient(), new ObjectMapper());

        String result = phrasing.phrase("我妈妈叫李芳");

        assertEquals("", result, "连接失败时应返回空串而不是抛异常");
    }

    @Test
    @DisplayName("失败路径：响应体不是合法 JSON 时返回空串")
    void 响应体不是合法JSON时返回空串() throws IOException {
        HttpServer broken = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        broken.createContext("/chat/completions", exchange -> {
            byte[] response = "not-json".getBytes("UTF-8");
            exchange.sendResponseHeaders(200, response.length);
            exchange.getResponseBody().write(response);
            exchange.close();
        });
        broken.start();
        try {
            LlmProperties props = new LlmProperties();
            props.setBaseUrl("http://127.0.0.1:" + broken.getAddress().getPort());
            props.setApiKey("k");
            props.setTimeoutSeconds(5);
            OpenAiCompatibleReplyPhrasing phrasing = new OpenAiCompatibleReplyPhrasing(
                    props, java.net.http.HttpClient.newHttpClient(), new ObjectMapper());

            String result = phrasing.phrase("我妈妈叫李芳");

            assertEquals("", result, "响应体非法时应返回空串");
        } finally {
            broken.stop(0);
        }
    }

    @Test
    @DisplayName("记忆内容为空时直接返回空串，不发起请求")
    void 记忆内容为空时直接返回空串() {
        OpenAiCompatibleReplyPhrasing phrasing = 生成器("test-key");

        String result = phrasing.phrase("   ");

        assertEquals("", result, "空记忆内容不应发起请求");
        assertTrue(lastRequestBody == null, "空记忆内容不应发出请求");
    }

    @Test
    @DisplayName("配置完整时启用标志为真")
    void 配置完整时启用标志为真() {
        LlmProperties props = new LlmProperties();
        props.setBaseUrl("https://example.invalid");
        props.setApiKey("k");

        assertTrue(props.enabled(), "基址与凭据都非空时应启用");
    }

    @Test
    @DisplayName("缺少凭据时不启用")
    void 缺少凭据时不启用() {
        LlmProperties props = new LlmProperties();
        props.setBaseUrl("https://example.invalid");
        props.setApiKey("");

        assertFalse(props.enabled(), "缺少凭据时不应启用");

        props.setApiKey("k");
        props.setBaseUrl("");
        assertFalse(props.enabled(), "缺少基址时不应启用");
    }
}
