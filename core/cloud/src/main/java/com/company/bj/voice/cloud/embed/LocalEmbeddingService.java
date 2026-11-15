package com.company.bj.voice.cloud.embed;

import com.company.bj.voice.cloud.config.EmbeddingProperties;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;

/**
 * 本地嵌入服务客户端。
 *
 * <p>调用随仓库走的本地 ONNX 嵌入服务（{@code core/edge/embedding/service.py}），
 * 走 OpenAI 兼容的 {@code POST /v1/embeddings} 协议。
 *
 * <p><b>为什么默认走本地而不是远端</b>：远端嵌入接口需要 API 凭据，
 * 而"克隆下来就能跑"是本作品面向求职场景的第一目标。
 * 本地模型（BGE-small-zh 量化 ONNX，22.9 MB）已实测具备可用判别力：
 * 同义句余弦 0.88，无关句 0.28。
 *
 * <p><b>响应顺序必须重排</b>：OpenAI 兼容接口不保证 {@code data} 数组的顺序
 * 与请求的 {@code input} 一致，因此按 {@code data[i].index} 重排后再返回。
 * 不重排会让向量与文本错位，表现为"检索永远召回不相关内容"——
 * 这是极难定位的一类问题。
 */
public class LocalEmbeddingService implements EmbeddingService {

    /** 嵌入接口的相对路径。 */
    private static final String EMBEDDINGS_PATH = "/v1/embeddings";

    /** 请求超时时间。 */
    private static final Duration REQUEST_TIMEOUT = Duration.ofSeconds(30);

    /** 请求头字段名：内容类型。 */
    private static final String HEADER_CONTENT_TYPE = "Content-Type";

    /** JSON 内容类型值。 */
    private static final String APPLICATION_JSON = "application/json";

    /** 响应体字段名：数据数组。 */
    private static final String FIELD_DATA = "data";

    /** 响应体字段名：单条数据的下标。 */
    private static final String FIELD_INDEX = "index";

    /** 响应体字段名：向量。 */
    private static final String FIELD_EMBEDDING = "embedding";

    /** HTTP 客户端。 */
    private final HttpClient httpClient;

    /** 嵌入配置。 */
    private final EmbeddingProperties props;

    /** JSON 解析器。 */
    private final ObjectMapper objectMapper;

    /**
     * 构造本地嵌入服务客户端。
     *
     * @param props 嵌入配置
     */
    public LocalEmbeddingService(EmbeddingProperties props) {
        this(props, HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build());
    }

    /**
     * 构造本地嵌入服务客户端。
     *
     * @param props      嵌入配置
     * @param httpClient HTTP 客户端
     */
    public LocalEmbeddingService(EmbeddingProperties props, HttpClient httpClient) {
        this.props = props;
        this.httpClient = httpClient;
        this.objectMapper = new ObjectMapper();
    }

    @Override
    public List<double[]> embed(List<String> texts) {
        if (texts == null || texts.isEmpty()) {
            return List.of();
        }

        String payload = writePayload(texts);
        HttpRequest request = HttpRequest.newBuilder()
            .uri(URI.create(props.getLocalEmbeddingBaseUrl() + EMBEDDINGS_PATH))
            .timeout(REQUEST_TIMEOUT)
            .header(HEADER_CONTENT_TYPE, APPLICATION_JSON)
            .POST(HttpRequest.BodyPublishers.ofString(payload))
            .build();

        try {
            HttpResponse<String> response = httpClient.send(request, HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() != 200) {
                throw new EmbeddingException("local embedding service returned status "
                    + response.statusCode() + ": " + response.body());
            }
            return parseVectors(response.body(), texts.size());
        } catch (IOException error) {
            throw new EmbeddingException("local embedding connect failed for "
                + props.getLocalEmbeddingBaseUrl() + EMBEDDINGS_PATH, error);
        } catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            throw new EmbeddingException("local embedding request interrupted", error);
        }
    }

    /**
     * 构造请求体。
     *
     * @param texts 待嵌入文本
     * @return JSON 文本
     */
    private String writePayload(List<String> texts) {
        StringBuilder builder = new StringBuilder("{\"input\":[");
        for (int index = 0; index < texts.size(); index++) {
            if (index > 0) {
                builder.append(',');
            }
            builder.append('"').append(escape(texts.get(index))).append('"');
        }
        builder.append("]}");
        return builder.toString();
    }

    /**
     * 转义 JSON 字符串中的特殊字符。
     *
     * @param value 原始字符串
     * @return 转义后的字符串内容（不含引号）
     */
    private String escape(String value) {
        StringBuilder builder = new StringBuilder(value.length());
        for (int index = 0; index < value.length(); index++) {
            char character = value.charAt(index);
            switch (character) {
                case '"' -> builder.append("\\\"");
                case '\\' -> builder.append("\\\\");
                case '\n' -> builder.append("\\n");
                case '\r' -> builder.append("\\r");
                case '\t' -> builder.append("\\t");
                default -> {
                    if (character < 0x20) {
                        builder.append(String.format("\\u%04x", (int) character));
                    } else {
                        builder.append(character);
                    }
                }
            }
        }
        return builder.toString();
    }

    /**
     * 解析响应并按请求下标重排向量。
     *
     * @param body      响应体
     * @param expected  期望的向量条数
     * @return 与入参等长的向量列表
     */
    private List<double[]> parseVectors(String body, int expected) {
        JsonNode root;
        try {
            root = objectMapper.readTree(body);
        } catch (IOException error) {
            throw new EmbeddingException("local embedding response is not valid json", error);
        }

        JsonNode data = root.path(FIELD_DATA);
        if (!data.isArray()) {
            throw new EmbeddingException("local embedding response has no data array: " + body);
        }

        // 按 index 重排：服务端不保证顺序，而顺序错位会让向量与文本对不上。
        double[][] ordered = new double[expected][];
        for (JsonNode item : data) {
            int index = item.path(FIELD_INDEX).asInt(-1);
            if (index < 0 || index >= expected) {
                continue;
            }
            JsonNode vector = item.path(FIELD_EMBEDDING);
            double[] values = new double[vector.size()];
            for (int position = 0; position < vector.size(); position++) {
                values[position] = vector.get(position).asDouble();
            }
            ordered[index] = values;
        }

        List<double[]> vectors = new ArrayList<>(expected);
        for (int index = 0; index < expected; index++) {
            if (ordered[index] == null) {
                throw new EmbeddingException(
                    "local embedding response is missing vector at index " + index);
            }
            vectors.add(ordered[index]);
        }
        return vectors;
    }
}
