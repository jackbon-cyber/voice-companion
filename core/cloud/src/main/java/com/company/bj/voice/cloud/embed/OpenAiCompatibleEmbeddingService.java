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
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * OpenAI 兼容模式的嵌入服务实现。
 *
 * <p>协议形如 {@code POST {baseUrl}/embeddings}，请求头 {@code Authorization: Bearer {apiKey}}，
 * 请求体 {@code {"model": model, "input": [...]}}，响应体形如
 * {@code {"data":[{"index":0,"embedding":[...]}, ...]}}。
 *
 * <p><b>两个必须处理的协议细节</b>：
 * <ul>
 *   <li>响应中 {@code data} 的顺序<b>不保证</b>与 {@code input} 一致，
 *       因此按 {@code data[i].index} 重排后再返回，否则向量会与输入文本错位，
 *       表现为"检索永远召回不相关内容"这类极难定位的问题；</li>
 *   <li>单次请求的条数有上限（默认 32），超出则按批拆分多次请求。</li>
 * </ul>
 *
 * <p><b>向量归一化</b>：本服务产出的向量一律归一化到<b>单位长度</b>。
 * 这是本工程唯一的向量产出点，写入路径与查询路径共用它，两侧尺度天然一致。
 * 归一化的必要性见 {@link EmbeddingNormalizer} 的类注释：
 * Chroma 返回的是平方 L2 距离，不归一化则距离随模长膨胀、得分失去区分度。
 *
 * <p>凭据只从环境变量注入，缺失时抛出 {@link EmbeddingException} 并在消息中指明环境变量名，
 * 源码与配置文件中不出现任何真实 api key。
 */
public class OpenAiCompatibleEmbeddingService implements EmbeddingService {

    /** 请求超时时间，避免单个慢请求拖垮整条链路。 */
    private static final Duration REQUEST_TIMEOUT = Duration.ofSeconds(60);

    /** 请求头字段名：授权。 */
    private static final String HEADER_AUTHORIZATION = "Authorization";

    /** 请求头字段名：内容类型。 */
    private static final String HEADER_CONTENT_TYPE = "Content-Type";

    /** 授权头的取值模板。 */
    private static final String BEARER_PREFIX = "Bearer ";

    /** JSON 内容类型值。 */
    private static final String APPLICATION_JSON = "application/json";

    /** 凭据来源的环境变量名，缺失凭据时在异常消息中指明。 */
    public static final String API_KEY_ENV = "DASHSCOPE_API_KEY";

    /** 嵌入接口的相对路径。 */
    private static final String EMBEDDINGS_PATH = "/embeddings";

    /** 请求体字段名：模型。 */
    private static final String FIELD_MODEL = "model";

    /** 请求体字段名：输入文本列表。 */
    private static final String FIELD_INPUT = "input";

    /** 响应体字段名：结果数组。 */
    private static final String FIELD_DATA = "data";

    /** 响应体字段名：结果在输入中的下标。 */
    private static final String FIELD_INDEX = "index";

    /** 响应体字段名：向量。 */
    private static final String FIELD_EMBEDDING = "embedding";

    /** 非 2xx 响应中错误消息最多保留的字符数，避免超长响应体淹没异常信息。 */
    private static final int ERROR_BODY_LIMIT = 500;

    private final EmbeddingProperties props;
    private final HttpClient httpClient;
    private final ObjectMapper mapper;

    /**
     * 构造嵌入服务。
     *
     * @param props     嵌入模型配置（基址、凭据、模型名、维度、批大小）
     * @param httpClient 用于发起请求的 HTTP 客户端
     * @param mapper    JSON 序列化与反序列化器
     */
    public OpenAiCompatibleEmbeddingService(EmbeddingProperties props, HttpClient httpClient, ObjectMapper mapper) {
        this.props = props;
        this.httpClient = httpClient;
        this.mapper = mapper;
    }

    @Override
    public List<double[]> embed(List<String> texts) {
        if (texts == null || texts.isEmpty()) {
            return List.of();
        }
        requireApiKey();

        List<double[]> vectors = new ArrayList<>(texts.size());
        int batchSize = Math.max(1, props.getBatchSize());
        for (int start = 0; start < texts.size(); start += batchSize) {
            List<String> batch = texts.subList(start, Math.min(start + batchSize, texts.size()));
            vectors.addAll(embedBatch(batch));
        }
        return vectors;
    }

    /**
     * 对一批文本发起一次嵌入请求。
     *
     * @param batch 本批文本
     * @return 与本批等长、顺序一一对应的向量列表
     * @throws EmbeddingException 网关返回非 2xx、响应无法解析或维度不符时抛出
     */
    private List<double[]> embedBatch(List<String> batch) {
        HttpResponse<String> response = send(batch);
        int status = response.statusCode();
        if (status < 200 || status >= 300) {
            throw new EmbeddingException("embedding request failed with status " + status
                + ", body: " + truncate(response.body()));
        }
        return parseVectors(response.body(), batch.size());
    }

    /**
     * 解析嵌入响应，按 {@code index} 重排并校验维度。
     *
     * @param body        响应体
     * @param expectedCount 期望的结果条数
     * @return 与期望条数等长的向量列表
     * @throws EmbeddingException 响应体无法解析、结果条数不符、index 越界或重复、维度不符时抛出
     */
    private List<double[]> parseVectors(String body, int expectedCount) {
        JsonNode root;
        try {
            root = mapper.readTree(body);
        } catch (IOException e) {
            throw new EmbeddingException("embedding response body is not valid json: " + truncate(body), e);
        }
        JsonNode data = root == null ? null : root.get(FIELD_DATA);
        if (data == null || !data.isArray()) {
            throw new EmbeddingException("embedding response missing 'data' array: " + truncate(body));
        }
        if (data.size() != expectedCount) {
            throw new EmbeddingException("embedding response returned " + data.size()
                + " results but " + expectedCount + " were requested");
        }

        // 按 index 重排：服务端不保证 data 的顺序与 input 一致。
        double[][] ordered = new double[expectedCount][];
        // seen 跟踪每个槽位是否已被占用：重复的 index 会覆盖前一个结果，
        // 使真正的缺失槽位留空，最终只报"缺少结果"—— 那是错误的原因。
        // 这里显式识别重复并单独报错，诊断信息才指向真正的病因。
        boolean[] seen = new boolean[expectedCount];
        for (JsonNode item : data) {
            JsonNode indexNode = item.get(FIELD_INDEX);
            JsonNode embeddingNode = item.get(FIELD_EMBEDDING);
            if (indexNode == null || embeddingNode == null || !embeddingNode.isArray()) {
                throw new EmbeddingException("embedding response item is malformed: " + item);
            }
            int index = indexNode.asInt();
            if (index < 0 || index >= expectedCount) {
                throw new EmbeddingException("embedding response index out of range: " + index);
            }
            if (seen[index]) {
                throw new EmbeddingException("embedding response contains duplicate index " + index);
            }
            seen[index] = true;
            ordered[index] = toVector(embeddingNode);
        }

        List<double[]> vectors = new ArrayList<>(expectedCount);
        for (int i = 0; i < expectedCount; i++) {
            if (ordered[i] == null) {
                throw new EmbeddingException("embedding response missing result at index " + i);
            }
            vectors.add(ordered[i]);
        }
        return vectors;
    }

    /**
     * 把 JSON 数组读成向量、校验维度并归一化到单位长度。
     *
     * <p><b>归一化为什么必须发生在这里</b>：本方法是本工程<b>唯一</b>的向量产出点，
     * 写入路径（摄取管线）与查询路径（检索端口）都经过它，因此两侧天然一致，
     * 不可能出现"存进去的是一种尺度、查的时候是另一种尺度"。
     *
     * <p><b>为什么需要归一化</b>：Chroma 的 {@code /query} 返回的距离是<b>平方</b> L2
     * （{@code sum((a_i - b_i)^2)}，已对 live Chroma 实测确认），而本工程把距离按
     * {@code score = 1 / (1 + distance)} 换算成相似度。若向量未归一化，
     * 距离会随向量模长与维度急剧膨胀，得分被系统性压到 0 附近
     * （实测中等模长的 1024 维向量距离已达 4~7，得分跌到 0.12~0.20），
     * 于是"语义相近"与"语义无关"的结果得分几乎无法区分，
     * 相似度下限也就失去了筛选作用。归一化后距离与模长无关，
     * 得分才有稳定语义。
     *
     * <p><b>零向量</b>：模长为 0 时无法归一化（除零会产生 NaN，进而污染下游距离），
     * 此处<b>原样返回零向量</b>。零向量与任何向量的平方 L2 等于对方模长的平方，
     * 得分固定为 {@code 1/(1+|v|^2)}，是确定且可解释的，不会产生 NaN。
     *
     * @param node 向量节点
     * @return 单位长度的向量；输入为零向量时原样返回零向量
     * @throws EmbeddingException 维度与配置不符时抛出
     */
    private double[] toVector(JsonNode node) {
        int expected = props.getDimensions();
        double[] vector = new double[node.size()];
        for (int i = 0; i < node.size(); i++) {
            vector[i] = node.get(i).asDouble();
        }
        if (vector.length != expected) {
            throw new EmbeddingException("embedding dimension mismatch: expected " + expected
                + " but got " + vector.length);
        }
        return EmbeddingNormalizer.normalize(vector);
    }

    /**
     * 发起一次嵌入请求。
     *
     * @param batch 本批文本
     * @return 原始响应
     * @throws EmbeddingException 连接失败、超时或请求中断时抛出
     */
    private HttpResponse<String> send(List<String> batch) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put(FIELD_MODEL, props.getModel());
        payload.put(FIELD_INPUT, batch);

        HttpRequest request = HttpRequest.newBuilder()
            .uri(URI.create(props.getRemoteBaseUrl() + EMBEDDINGS_PATH))
            .timeout(REQUEST_TIMEOUT)
            .header(HEADER_AUTHORIZATION, BEARER_PREFIX + props.getApiKey())
            .header(HEADER_CONTENT_TYPE, APPLICATION_JSON)
            .POST(HttpRequest.BodyPublishers.ofString(writeJson(payload)))
            .build();

        try {
            return httpClient.send(request, HttpResponse.BodyHandlers.ofString());
        } catch (IOException e) {
            throw new EmbeddingException("embedding connect failed for " + props.getRemoteBaseUrl() + EMBEDDINGS_PATH, e);
        } catch (InterruptedException e) {
            // 恢复中断标记，避免吞掉中断信号导致上层无法感知取消。
            Thread.currentThread().interrupt();
            throw new EmbeddingException("embedding request interrupted for " + props.getRemoteBaseUrl() + EMBEDDINGS_PATH, e);
        }
    }

    /**
     * 校验凭据是否存在。
     *
     * @throws EmbeddingException 凭据为空时抛出，消息中指明环境变量名
     */
    private void requireApiKey() {
        String apiKey = props.getApiKey();
        if (apiKey == null || apiKey.isBlank()) {
            throw new EmbeddingException("embedding api key is not configured, please set the "
                + API_KEY_ENV + " environment variable");
        }
    }

    /**
     * 把请求体序列化为 JSON 字符串。
     *
     * @param payload 请求体
     * @return JSON 字符串
     * @throws EmbeddingException 序列化失败时抛出
     */
    private String writeJson(Map<String, Object> payload) {
        try {
            return mapper.writeValueAsString(payload);
        } catch (IOException e) {
            throw new EmbeddingException("embedding request body is not serializable: " + payload, e);
        }
    }

    /**
     * 截断过长的响应体片段，避免异常信息被巨量文本淹没。
     *
     * @param body 响应体
     * @return 截断后的响应体
     */
    private String truncate(String body) {
        if (body == null) {
            return "";
        }
        if (body.length() <= ERROR_BODY_LIMIT) {
            return body;
        }
        return body.substring(0, ERROR_BODY_LIMIT) + "...";
    }
}
