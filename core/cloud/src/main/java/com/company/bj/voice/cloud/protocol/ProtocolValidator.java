package com.company.bj.voice.cloud.protocol;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SchemaValidatorsConfig;
import com.networknt.schema.SpecVersion.VersionFlag;
import com.networknt.schema.ValidationMessage;
import com.networknt.schema.resource.SchemaMappers;
import java.io.IOException;import java.io.UncheckedIOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 端云协议校验器。
 *
 * <p>Java 侧与 Python 侧读**同一份** schema 文件（{@code core/protocol/schema/}），
 * 不各写一份 —— 两份 schema 必然会漂移，而漂移的表现是"某些消息端侧认为合法、
 * 云端认为非法"，排查成本极高。
 *
 * <p>schema 按名称缓存，避免每条消息都重新读盘解析。
 */
public class ProtocolValidator {

    /** 协议 schema 的 URI 前缀。 */
    private static final String SCHEMA_URI_PREFIX = "https://voice-companion/protocol/";

    /** schema 名到已编译 schema 的缓存。 */
    private final Map<String, JsonSchema> schemaCache = new ConcurrentHashMap<>();

    /** schema 所在目录。 */
    private final Path schemaDirectory;

    /** JSON 解析器。 */
    private final ObjectMapper objectMapper = new ObjectMapper();

    /**
     * 构造协议校验器。
     *
     * @param schemaDirectory schema 所在目录，不能为 null
     * @throws IllegalArgumentException {@code schemaDirectory} 为 null 时抛出
     */
    public ProtocolValidator(Path schemaDirectory) {
        if (schemaDirectory == null) {
            throw new IllegalArgumentException("schemaDirectory must not be null");
        }
        this.schemaDirectory = schemaDirectory;
    }

    /**
     * 校验一条消息。
     *
     * @param schemaName schema 名（不含 {@code .schema.json} 后缀）
     * @param jsonPayload 消息 JSON 文本
     * @return 错误列表，空列表表示校验通过
     */
    public List<String> validate(String schemaName, String jsonPayload) {
        JsonSchema schema = loadSchema(schemaName);
        if (schema == null) {
            return List.of("未知协议 schema：" + schemaName);
        }

        JsonNode node;
        try {
            node = objectMapper.readTree(jsonPayload);
        } catch (IOException error) {
            return List.of("消息不是合法 JSON：" + error.getMessage());
        }

        List<String> errors = new ArrayList<>();
        for (ValidationMessage message : schema.validate(node)) {
            errors.add(describe(message));
        }
        return errors;
    }

    private JsonSchema loadSchema(String schemaName) {
        if (schemaName == null) {
            return null;
        }
        return schemaCache.computeIfAbsent(schemaName, this::readSchema);
    }

    private JsonSchema readSchema(String schemaName) {
        Path schemaPath = schemaDirectory.resolve(schemaName + ".schema.json");
        if (!Files.exists(schemaPath)) {
            return null;
        }
        try {
            String content = Files.readString(schemaPath);
            JsonSchemaFactory factory = buildSchemaFactory();
            SchemaValidatorsConfig config = SchemaValidatorsConfig.builder().build();
            return factory.getSchema(content, config);
        } catch (IOException error) {
            throw new UncheckedIOException("读取协议 schema 失败：" + schemaPath, error);
        }
    }

    /**
     * 构建 schema 工厂。
     *
     * <p>协议 schema 之间存在相对引用（例如 {@code session.schema.json} 引用
     * {@code audio-negotiation.schema.json}）。默认行为是把这些相对引用当成
     * 远程 URL 去下载，既慢又会打网络。这里把协议域名映射到本地目录，
     * 让引用在本地解析。
     *
     * @return schema 工厂
     */
    private JsonSchemaFactory buildSchemaFactory() {
        String localPrefix = schemaDirectory.toUri().toString();
        return JsonSchemaFactory.getInstance(
                VersionFlag.V202012,
                builder -> builder.schemaMappers(mappers -> mappers.mapPrefix(SCHEMA_URI_PREFIX, localPrefix)));
    }

    private String describe(ValidationMessage message) {
        String instanceLocation = message.getInstanceLocation() == null
                ? ""
                : message.getInstanceLocation().toString();
        return "字段 " + (instanceLocation.isEmpty() ? "(根)" : instanceLocation) + "：" + message.getMessage();
    }
}
