package com.company.bj.voice.cloud.embed;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.company.bj.voice.cloud.config.EmbeddingProperties;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import com.sun.net.httpserver.HttpServer;
import java.util.List;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * {@link LocalEmbeddingService} 的行为测试。
 *
 * <p>用内嵌的 HTTP 服务模拟本地嵌入服务，重点验证
 * <b>响应顺序重排</b> —— 服务端不保证 {@code data} 顺序，
 * 顺序错位会让向量与文本对不上。
 */
class LocalEmbeddingServiceTest {

    /** 内嵌 HTTP 服务。 */
    private HttpServer server;

    /** 服务基址。 */
    private String baseUrl;

    /** 最近一次收到的请求体。 */
    private volatile String lastRequestBody;

    /** 本次要返回的响应体。 */
    private volatile String responseBody = "{\"data\":[]}";

    /** 本次要返回的 HTTP 状态码。 */
    private volatile int responseStatus = 200;

    @BeforeEach
    void setUp() throws IOException {
        server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/v1/embeddings", exchange -> {
            lastRequestBody = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);
            byte[] body = responseBody.getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().add("Content-Type", "application/json");
            exchange.sendResponseHeaders(responseStatus, body.length);
            exchange.getResponseBody().write(body);
            exchange.close();
        });
        server.start();
        baseUrl = "http://127.0.0.1:" + server.getAddress().getPort();
    }

    @AfterEach
    void tearDown() {
        server.stop(0);
    }

    /**
     * 构造被测客户端。
     *
     * @return 客户端
     */
    private LocalEmbeddingService service() {
        EmbeddingProperties props = new EmbeddingProperties();
        props.setLocalEmbeddingBaseUrl(baseUrl);
        return new LocalEmbeddingService(props);
    }

    @Test
    @DisplayName("按响应中的下标重排向量")
    void 按响应中的下标重排向量() {
        // 服务端故意乱序返回：index 1 在前，index 0 在后。
        responseBody = """
            {"data":[
              {"index":1,"embedding":[0.3,0.4]},
              {"index":0,"embedding":[0.1,0.2]}
            ]}""";

        List<double[]> vectors = service().embed(List.of("甲", "乙"));

        assertEquals(2, vectors.size());
        assertArrayEquals(new double[] {0.1, 0.2}, vectors.get(0), 1e-9);
        assertArrayEquals(new double[] {0.3, 0.4}, vectors.get(1), 1e-9);
    }

    @Test
    @DisplayName("请求体包含全部待嵌入文本")
    void 请求体包含全部待嵌入文本() {
        responseBody = """
            {"data":[{"index":0,"embedding":[0.1]}]}""";

        service().embed(List.of("我妈妈叫李芳"));

        assertTrue(lastRequestBody.contains("我妈妈叫李芳"), lastRequestBody);
    }

    @Test
    @DisplayName("空输入列表直接返回空结果而不发请求")
    void 空输入列表直接返回空结果而不发请求() {
        assertEquals(List.of(), service().embed(List.of()));
    }

    @Test
    @DisplayName("非二〇〇状态码抛出异常且消息含状态码")
    void 非二〇〇状态码抛出异常且消息含状态码() {
        responseStatus = 503;
        responseBody = "{\"error\":{\"message\":\"model missing\"}}";

        EmbeddingException error = assertThrows(EmbeddingException.class,
            () -> service().embed(List.of("测试")));

        assertTrue(error.getMessage().contains("503"), error.getMessage());
    }

    @Test
    @DisplayName("响应缺少某个下标时抛出异常")
    void 响应缺少某个下标时抛出异常() {
        responseBody = """
            {"data":[{"index":0,"embedding":[0.1]}]}""";

        EmbeddingException error = assertThrows(EmbeddingException.class,
            () -> service().embed(List.of("甲", "乙")));

        assertTrue(error.getMessage().contains("index 1"), error.getMessage());
    }

    @Test
    @DisplayName("响应不是合法 JSON 时抛出异常")
    void 响应不是合法JSON时抛出异常() {
        responseBody = "not a json";

        EmbeddingException error = assertThrows(EmbeddingException.class,
            () -> service().embed(List.of("测试")));

        assertTrue(error.getMessage().contains("json"), error.getMessage());
    }
}
