package com.company.bj.voice.cloud.chroma;

import com.company.bj.voice.cloud.config.ChromaProperties;
import com.fasterxml.jackson.core.type.TypeReference;
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
 * Chroma v2 REST 客户端。
 *
 * <p>封装知识库与长期记忆所需的全部集合操作：建集合、写记录、读记录、按元数据过滤检索、
 * 计数与删除。所有路径都由 {@link ChromaPaths} 统一构造，基址与租户/数据库来自
 * {@link ChromaProperties}。
 *
 * <p><b>协议要点</b>（均已对真实 Chroma v2 服务逐项验证）：
 * <ul>
 *   <li>{@code /query} 响应中的 {@code ids} / {@code documents} / {@code metadatas} / {@code distances}
 *       是<b>二维</b>数组，外层维度等于查询条数；</li>
 *   <li>{@code /get} 响应中的同名字段是<b>一维</b>数组；</li>
 *   <li>{@code /update} 的 {@code metadatas} 必须是<b>数组</b>，长度与 {@code ids} 一致，
 *       传裸对象会被服务端以 "expected a sequence" 拒绝；</li>
 *   <li>{@code where} 缺省时整个字段不出现，Chroma v2 接受缺省。</li>
 * </ul>
 */
public class ChromaClient {

    /** 请求超时时间，避免单个慢请求拖垮整条链路。 */
    private static final Duration REQUEST_TIMEOUT = Duration.ofSeconds(30);

    /** 请求头中的内容类型字段名。 */
    private static final String HEADER_CONTENT_TYPE = "Content-Type";

    /** JSON 内容类型值。 */
    private static final String APPLICATION_JSON = "application/json";

    /** 非 2xx 响应中错误消息最多保留的字符数，避免超长响应体淹没异常信息。 */
    private static final int ERROR_BODY_LIMIT = 500;

    /** 请求体字段名：记录 id。 */
    private static final String FIELD_IDS = "ids";

    /** 请求体字段名：向量。 */
    private static final String FIELD_EMBEDDINGS = "embeddings";

    /** 请求体字段名：文档文本。 */
    private static final String FIELD_DOCUMENTS = "documents";

    /** 请求体字段名：元数据。 */
    private static final String FIELD_METADATAS = "metadatas";

    /** 请求体字段名：集合名。 */
    private static final String FIELD_NAME = "name";

    /** 请求体字段名：集合存在时是否复用。 */
    private static final String FIELD_GET_OR_CREATE = "get_or_create";

    /** 请求体字段名：查询向量。 */
    private static final String FIELD_QUERY_EMBEDDINGS = "query_embeddings";

    /** 请求体字段名：返回条数。 */
    private static final String FIELD_N_RESULTS = "n_results";

    /** 请求体字段名：元数据过滤条件。 */
    private static final String FIELD_WHERE = "where";

    /** 请求体字段名：需返回的字段。 */
    private static final String FIELD_INCLUDE = "include";

    /** 请求体字段名：返回条数上限，用于分页读取。 */
    private static final String FIELD_LIMIT = "limit";

    /** 请求体字段名：跳过的记录数，用于分页读取。 */
    private static final String FIELD_OFFSET = "offset";

    /** 响应字段名：记录条数。 */
    private static final String FIELD_COUNT = "count";

    /** 响应字段名：删除操作报告的删除条数。 */
    private static final String FIELD_DELETED = "deleted";

    /** 响应字段名：命中距离。 */
    private static final String FIELD_DISTANCES = "distances";

    /** 集合子路径后缀：追加记录。 */
    private static final String SUB_PATH_ADD = "/add";

    /** 集合子路径后缀：覆盖写入。 */
    private static final String SUB_PATH_UPSERT = "/upsert";

    /** 集合子路径后缀：改写元数据。 */
    private static final String SUB_PATH_UPDATE = "/update";

    /** 集合子路径后缀：按 id 读取。 */
    private static final String SUB_PATH_GET = "/get";

    /** 集合子路径后缀：向量检索。 */
    private static final String SUB_PATH_QUERY = "/query";

    /** 集合子路径后缀：统计条数。 */
    private static final String SUB_PATH_COUNT = "/count";

    /** 集合子路径后缀：按 id 删除。 */
    private static final String SUB_PATH_DELETE = "/delete";

    private final ChromaProperties props;
    private final HttpClient httpClient;
    private final ObjectMapper mapper;

    /**
     * 构造 Chroma 客户端。
     *
     * @param props     Chroma 服务与集合配置
     * @param httpClient 用于发起请求的 HTTP 客户端
     * @param mapper    JSON 序列化与反序列化器
     */
    public ChromaClient(ChromaProperties props, HttpClient httpClient, ObjectMapper mapper) {
        this.props = props;
        this.httpClient = httpClient;
        this.mapper = mapper;
    }

    /**
     * 读取 Chroma 服务端版本号。
     *
     * @return 服务端版本号，例如 {@code 1.0.0}
     * @throws ChromaException 服务端返回非 2xx、连接失败或响应体无法解析
     */
    public String version() {
        JsonNode body = exchange("GET", ChromaPaths.version(), null);
        // 服务端返回的是裸 JSON 字符串（如 "1.0.0"）而非对象，故直接取其文本内容。
        return body.asText();
    }

    /**
     * 创建集合，若同名集合已存在则直接复用其 id。
     *
     * <p>集合名会先经 {@link ChromaCollectionName#validate(String)} 校验，
     * 非法名称在发起 HTTP 请求之前即被拒绝。
     *
     * @param name 集合名
     * @return 集合 id
     * @throws IllegalArgumentException 集合名非法
     * @throws ChromaException           服务端返回非 2xx、连接失败或响应体无法解析
     */
    public String createCollection(String name) {
        String validated = ChromaCollectionName.validate(name);
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put(FIELD_NAME, validated);
        payload.put(FIELD_GET_OR_CREATE, Boolean.TRUE);

        JsonNode body = exchange("POST", ChromaPaths.collections(props.getTenant(), props.getDatabase()), payload);
        JsonNode idNode = body.get("id");
        if (idNode == null || idNode.isNull()) {
            throw new ChromaException("chroma create collection response missing 'id' field: " + body);
        }
        return idNode.asText();
    }

    /**
     * 列出当前租户/数据库下的全部集合 id。
     *
     * @return 集合 id 列表
     * @throws ChromaException 服务端返回非 2xx、连接失败或响应体无法解析
     */
    public List<String> listCollections() {
        JsonNode body = exchange("GET", ChromaPaths.collections(props.getTenant(), props.getDatabase()), null);
        if (!body.isArray()) {
            throw new ChromaException("chroma list collections response is not an array: " + body);
        }
        List<String> ids = new ArrayList<>(body.size());
        for (JsonNode item : body) {
            JsonNode idNode = item.get("id");
            if (idNode != null && !idNode.isNull()) {
                ids.add(idNode.asText());
            }
        }
        return ids;
    }

    /**
     * 向集合追加记录，已存在的 id 会被服务端拒绝。
     *
     * @param collectionId 集合 id
     * @param ids          记录 id 列表
     * @param embeddings   向量列表，与 {@code ids} 等长
     * @param documents    文档文本列表，与 {@code ids} 等长
     * @param metadatas    元数据列表，与 {@code ids} 等长
     * @throws ChromaException 服务端返回非 2xx、连接失败或响应体无法解析
     */
    public void add(String collectionId, List<String> ids, List<double[]> embeddings,
        List<String> documents, List<Map<String, Object>> metadatas) {
        exchange("POST", collectionPath(collectionId) + SUB_PATH_ADD,
            recordPayload(ids, embeddings, documents, metadatas));
    }

    /**
     * 写入集合记录，已存在的 id 被覆盖，不存在的 id 被新增。
     *
     * <p>摄取管线一律走本方法而非 {@link #add}，以此保证重复摄取时结果幂等。
     *
     * @param collectionId 集合 id
     * @param ids          记录 id 列表
     * @param embeddings   向量列表，与 {@code ids} 等长
     * @param documents    文档文本列表，与 {@code ids} 等长
     * @param metadatas    元数据列表，与 {@code ids} 等长
     * @throws ChromaException 服务端返回非 2xx、连接失败或响应体无法解析
     */
    public void upsert(String collectionId, List<String> ids, List<double[]> embeddings,
        List<String> documents, List<Map<String, Object>> metadatas) {
        exchange("POST", collectionPath(collectionId) + SUB_PATH_UPSERT,
            recordPayload(ids, embeddings, documents, metadatas));
    }

    /**
     * 改写单条记录的元数据，文档与向量保持不变。
     *
     * @param collectionId 集合 id
     * @param id           记录 id
     * @param metadata     新的元数据
     * @throws ChromaException 服务端返回非 2xx、连接失败或响应体无法解析
     */
    public void update(String collectionId, String id, Map<String, Object> metadata) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put(FIELD_IDS, List.of(id));
        // 服务端要求 metadatas 为数组（与 ids 等长），单条记录也要包成一维数组。
        payload.put(FIELD_METADATAS, List.of(metadata));

        exchange("POST", collectionPath(collectionId) + SUB_PATH_UPDATE, payload);
    }

    /**
     * 按记录 id 读取集合中的记录。
     *
     * <p>注意与 {@link #query} 的差异：本方法的响应字段是<b>一维</b>数组。
     *
     * @param collectionId 集合 id
     * @param ids          记录 id 列表
     * @return 读取到的记录
     * @throws ChromaException 服务端返回非 2xx、连接失败或响应体无法解析
     */
    public ChromaGetResult get(String collectionId, List<String> ids) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put(FIELD_IDS, ids);

        JsonNode body = exchange("POST", collectionPath(collectionId) + SUB_PATH_GET, payload);
        return new ChromaGetResult(
            readStringList(body.get(FIELD_IDS)),
            readStringList(body.get(FIELD_DOCUMENTS)),
            readMetadataList(body.get(FIELD_METADATAS)));
    }

    /**
     * 按元数据过滤条件读取集合记录。
     *
     * <p><b>与 {@link #get} 的语义差异（已对 live Chroma v2 实测确认）</b>：
     * <ul>
     *   <li>本方法<b>不传 {@code ids}</b> 字段 —— 服务端把「缺省 {@code ids}」
     *       解释为"读取全部匹配记录"，而 {@code ids: []}（空数组）
     *       被解释为"一条也不要"，返回空列表。</li>
     *   <li>{@code where} 支持 {@code $and} / {@code $or} 组合与
     *       {@code $eq} / {@code $gt} / {@code $gte} / {@code $lt} / {@code $lte} 比较。</li>
     *   <li>{@code limit} 与 {@code offset} 支持分页；缺省 {@code limit} 时返回全部匹配记录。</li>
     * </ul>
     *
     * @param collectionId 集合 id
     * @param where        元数据过滤条件，为 {@code null} 时不向服务端发送该字段
     * @param limit        返回条数上限，为 {@code null} 或非正数时不施加限制
     * @param offset       跳过的记录数，用于分页
     * @param include      需要返回的字段，例如 {@code documents} / {@code metadatas}
     * @return 读取到的记录
     * @throws ChromaException 服务端返回非 2xx、连接失败或响应体无法解析
     */
    public ChromaGetResult getByWhere(String collectionId, Map<String, Object> where,
        Integer limit, Integer offset, List<String> include) {
        Map<String, Object> payload = new LinkedHashMap<>();
        if (where != null) {
            payload.put(FIELD_WHERE, where);
        }
        if (limit != null && limit > 0) {
            payload.put(FIELD_LIMIT, limit);
        }
        if (offset != null && offset > 0) {
            payload.put(FIELD_OFFSET, offset);
        }
        if (include != null && !include.isEmpty()) {
            payload.put(FIELD_INCLUDE, include);
        }

        JsonNode body = exchange("POST", collectionPath(collectionId) + SUB_PATH_GET, payload);
        return new ChromaGetResult(
            readStringList(body.get(FIELD_IDS)),
            readStringList(body.get(FIELD_DOCUMENTS)),
            readMetadataList(body.get(FIELD_METADATAS)));
    }

    /**
     * 按向量相似度检索集合记录，可叠加元数据过滤条件。
     *
     * @param collectionId   集合 id
     * @param queryEmbedding 查询向量
     * @param nResults       返回条数
     * @param where          元数据过滤条件，为 {@code null} 时不向服务端发送该字段
     * @param include        需要返回的字段，例如 {@code documents} / {@code metadatas} / {@code distances}
     * @return 检索结果，字段均为二维数组，外层维度等于查询条数
     * @throws ChromaException 服务端返回非 2xx、连接失败或响应体无法解析
     */
    public ChromaQueryResult query(String collectionId, double[] queryEmbedding, int nResults,
        Map<String, Object> where, List<String> include) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put(FIELD_QUERY_EMBEDDINGS, List.of(queryEmbedding));
        payload.put(FIELD_N_RESULTS, nResults);
        if (where != null) {
            payload.put(FIELD_WHERE, where);
        }
        if (include != null && !include.isEmpty()) {
            payload.put(FIELD_INCLUDE, include);
        }

        JsonNode body = exchange("POST", collectionPath(collectionId) + SUB_PATH_QUERY, payload);
        return new ChromaQueryResult(
            readNestedStringList(body.get(FIELD_IDS)),
            readNestedStringList(body.get(FIELD_DOCUMENTS)),
            readNestedMetadataList(body.get(FIELD_METADATAS)),
            readNestedDoubleList(body.get(FIELD_DISTANCES)));
    }

    /**
     * 统计集合中的记录条数。
     *
     * <p>本机 Chroma v2 服务返回的是裸 JSON 数字（如 {@code 2}），部分版本返回
     * {@code {"count": 2}} 对象，此处两种形态都接受。
     *
     * @param collectionId 集合 id
     * @return 记录条数
     * @throws ChromaException 服务端返回非 2xx、连接失败或响应体无法解析
     */
    public long count(String collectionId) {
        JsonNode body = exchange("GET", collectionPath(collectionId) + SUB_PATH_COUNT, null);
        if (body.isNumber()) {
            return body.asLong();
        }
        JsonNode countNode = body.get(FIELD_COUNT);
        if (countNode == null || countNode.isNull()) {
            throw new ChromaException("chroma count response missing 'count' field: " + body);
        }
        return countNode.asLong();
    }

    /**
     * 按记录 id 删除集合中的记录。
     *
     * @param collectionId 集合 id
     * @param ids          待删除的记录 id 列表
     * @throws ChromaException 服务端返回非 2xx、连接失败或响应体无法解析
     */
    public void delete(String collectionId, List<String> ids) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put(FIELD_IDS, ids);

        exchange("POST", collectionPath(collectionId) + SUB_PATH_DELETE, payload);
    }

    /**
     * 按元数据过滤条件删除集合中的记录。
     *
     * <p>服务端支持在 {@code where} 过滤下删除（已对 live Chroma v2 实测确认），
     * 因此删除一个文档的全部切片无需先把切片 id 拉回应用层 ——
     * 省掉一次全量读，也避免「读了切片 id 但删除前集合已变」的竞态。
     *
     * <p><b>返回服务端报告的实际删除条数</b>：服务端响应形如
     * {@code {"deleted": 2}}。调用方需要这个数字来确认清理是否真的生效 ——
     * "以为清干净了但其实没删掉"是比"没清理"更危险的状态。
     *
     * @param collectionId 集合 id
     * @param where        元数据过滤条件，为 {@code null} 时不向服务端发送该字段
     * @return 服务端报告的删除条数
     * @throws ChromaException 服务端返回非 2xx、连接失败或响应体无法解析
     */
    public int deleteByWhere(String collectionId, Map<String, Object> where) {
        Map<String, Object> payload = new LinkedHashMap<>();
        if (where != null) {
            payload.put(FIELD_WHERE, where);
        }

        JsonNode body = exchange("POST", collectionPath(collectionId) + SUB_PATH_DELETE, payload);
        JsonNode deleted = body.get(FIELD_DELETED);
        return deleted == null || deleted.isNull() ? 0 : deleted.asInt();
    }

    /**
     * 构造记录写入类请求体，四个数组长度一致。
     *
     * @param ids        记录 id 列表
     * @param embeddings 向量列表
     * @param documents  文档文本列表
     * @param metadatas  元数据列表
     * @return 请求体
     */
    private Map<String, Object> recordPayload(List<String> ids, List<double[]> embeddings,
        List<String> documents, List<Map<String, Object>> metadatas) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put(FIELD_IDS, ids);
        payload.put(FIELD_EMBEDDINGS, embeddings);
        payload.put(FIELD_DOCUMENTS, documents);
        payload.put(FIELD_METADATAS, metadatas);
        return payload;
    }

    /**
     * 构造某个集合的相对路径。
     *
     * @param collectionId 集合 id
     * @return 相对路径
     */
    private String collectionPath(String collectionId) {
        return ChromaPaths.collection(props.getTenant(), props.getDatabase(), collectionId);
    }

    /**
     * 发起 HTTP 请求并解析响应。
     *
     * @param method  HTTP 方法
     * @param path    相对路径
     * @param payload 请求体，为 {@code null} 时表示无请求体
     * @return 解析后的响应 JSON 节点
     * @throws ChromaException 服务端返回非 2xx、连接失败或响应体无法解析
     */
    private JsonNode exchange(String method, String path, Map<String, Object> payload) {
        HttpResponse<String> response = send(method, path, payload);
        int status = response.statusCode();
        if (status < 200 || status >= 300) {
            throw new ChromaException("chroma request failed with status " + status + " for " + method + " " + path
                + ", body: " + truncate(response.body()));
        }
        try {
            JsonNode node = mapper.readTree(response.body());
            return node == null ? mapper.createObjectNode() : node;
        } catch (IOException e) {
            throw new ChromaException("chroma response body is not valid json for " + method + " " + path
                + ", body: " + truncate(response.body()), e);
        }
    }

    /**
     * 发起 HTTP 请求，把传输层异常统一转换为 {@link ChromaException}。
     *
     * @param method  HTTP 方法
     * @param path    相对路径
     * @param payload 请求体，为 {@code null} 时表示无请求体
     * @return 原始响应
     * @throws ChromaException 连接失败、超时或请求中断
     */
    private HttpResponse<String> send(String method, String path, Map<String, Object> payload) {
        HttpRequest.Builder builder = HttpRequest.newBuilder()
            .uri(URI.create(props.getBaseUrl() + path))
            .timeout(REQUEST_TIMEOUT)
            .header(HEADER_CONTENT_TYPE, APPLICATION_JSON);

        String body = payload == null ? null : writeJson(payload);
        HttpRequest.BodyPublisher publisher = body == null
            ? HttpRequest.BodyPublishers.noBody()
            : HttpRequest.BodyPublishers.ofString(body);
        builder.method(method, publisher);

        try {
            return httpClient.send(builder.build(), HttpResponse.BodyHandlers.ofString());
        } catch (IOException e) {
            throw new ChromaException("chroma connect failed for " + method + " " + props.getBaseUrl() + path, e);
        } catch (InterruptedException e) {
            // 恢复中断标记，避免吞掉中断信号导致上层无法感知取消。
            Thread.currentThread().interrupt();
            throw new ChromaException("chroma request interrupted for " + method + " " + props.getBaseUrl() + path, e);
        }
    }

    /**
     * 把请求体序列化为 JSON 字符串。
     *
     * @param payload 请求体
     * @return JSON 字符串
     * @throws ChromaException 序列化失败
     */
    private String writeJson(Map<String, Object> payload) {
        try {
            return mapper.writeValueAsString(payload);
        } catch (IOException e) {
            throw new ChromaException("chroma request body is not serializable: " + payload, e);
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

    /**
     * 读取一维字符串数组。
     *
     * @param node JSON 节点
     * @return 字符串列表，节点缺失或为 null 时返回空列表
     */
    private List<String> readStringList(JsonNode node) {
        if (node == null || node.isNull() || !node.isArray()) {
            return List.of();
        }
        List<String> values = new ArrayList<>(node.size());
        for (JsonNode item : node) {
            values.add(item.isNull() ? null : item.asText());
        }
        return values;
    }

    /**
     * 读取一维元数据数组。
     *
     * @param node JSON 节点
     * @return 元数据列表，节点缺失或为 null 时返回空列表
     */
    private List<Map<String, Object>> readMetadataList(JsonNode node) {
        if (node == null || node.isNull() || !node.isArray()) {
            return List.of();
        }
        List<Map<String, Object>> values = new ArrayList<>(node.size());
        for (JsonNode item : node) {
            values.add(readMetadata(item));
        }
        return values;
    }

    /**
     * 读取二维字符串数组（外层维度等于查询条数）。
     *
     * @param node JSON 节点
     * @return 嵌套字符串列表
     */
    private List<List<String>> readNestedStringList(JsonNode node) {
        if (node == null || node.isNull() || !node.isArray()) {
            return List.of();
        }
        List<List<String>> values = new ArrayList<>(node.size());
        for (JsonNode item : node) {
            values.add(readStringList(item));
        }
        return values;
    }

    /**
     * 读取二维元数据数组（外层维度等于查询条数）。
     *
     * @param node JSON 节点
     * @return 嵌套元数据列表
     */
    private List<List<Map<String, Object>>> readNestedMetadataList(JsonNode node) {
        if (node == null || node.isNull() || !node.isArray()) {
            return List.of();
        }
        List<List<Map<String, Object>>> values = new ArrayList<>(node.size());
        for (JsonNode item : node) {
            values.add(readMetadataList(item));
        }
        return values;
    }

    /**
     * 读取二维数值数组（外层维度等于查询条数）。
     *
     * @param node JSON 节点
     * @return 嵌套数值列表
     */
    private List<List<Double>> readNestedDoubleList(JsonNode node) {
        if (node == null || node.isNull() || !node.isArray()) {
            return List.of();
        }
        List<List<Double>> values = new ArrayList<>(node.size());
        for (JsonNode item : node) {
            List<Double> row = new ArrayList<>(item.size());
            for (JsonNode cell : item) {
                row.add(cell.isNull() ? null : cell.asDouble());
            }
            values.add(row);
        }
        return values;
    }

    /**
     * 把单个 JSON 对象读成元数据 Map。
     *
     * @param node JSON 节点
     * @return 元数据 Map，节点不是对象时返回空 Map
     */
    private Map<String, Object> readMetadata(JsonNode node) {
        if (node == null || node.isNull() || !node.isObject()) {
            return Map.of();
        }
        return mapper.convertValue(node, new TypeReference<Map<String, Object>>() {
        });
    }
}
