package com.company.bj.voice.cloud.protocol;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SchemaValidatorsConfig;
import com.networknt.schema.SpecVersion.VersionFlag;
import com.networknt.schema.ValidationMessage;
import com.networknt.schema.resource.ClasspathSchemaLoader;
import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
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

    /**
     * schema 在 jar 内的 classpath 位置。
     *
     * <p>★ 这条 classpath 路径是**部署能否正确工作**的关键：
     * 协议 schema 住在 {@code core/protocol/schema/}，不在 cloud 模块内，
     * 所以必须由构建显式打进 jar（见 pom.xml 的 {@code <resources>}）。
     *
     * <p>曾经只按"相对工作目录的路径"找 schema（{@code ../protocol/schema}），
     * 那在源码目录里跑恰好成立，**打成 jar 部署后就不存在了** ——
     * 每条上行消息都被判"未知协议 schema"而丢弃。
     * 而云端会退回降级话术继续对话，**看不出异常**，
     * 实际是协议校验完全失效。
     */
    private static final String CLASSPATH_SCHEMA_ROOT = "protocol/schema";

    /**
     * classpath 方案的 IRI 前缀。
     *
     * <p>协议域名映射到这个前缀后，{@code ClasspathSchemaLoader} 就能
     * 用 {@code getResourceAsStream} 把引用读出来 —— 这在 jar 内是唯一
     * 可行的读法。
     */
    private static final String CLASSPATH_IRI_PREFIX = "classpath:" + CLASSPATH_SCHEMA_ROOT + "/";

    /**
     * 启动期必须能加载到的协议 schema。
     *
     * <p>覆盖端云双向的全部消息类型 —— 少一个都会让对应消息静默失效。
     */
    private static final List<String> REQUIRED_SCHEMA_NAMES = List.of(
            "session",
            "audio-negotiation",
            "audio-frame",
            "intent-report",
            "text-reply",
            "voice-chunk",
            "control-channel",
            "degrade-level");

    /** schema 名到已编译 schema 的缓存。 */
    private final Map<String, JsonSchema> schemaCache = new ConcurrentHashMap<>();

    /** schema 所在目录（开发期从源码树读的备用位置）。 */
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

    /**
     * 启动期自检：确认全部协议 schema 都能加载并编译。
     *
     * <p>★ 这个方法存在的唯一理由是让"schema 缺失"变成**启动失败**，
     * 而不是运行期的静默降级。
     *
     * <p>没有它时的失败形态：每条上行消息都被判"未知协议 schema"，
     * 云端退回降级话术继续对话 —— 现象是"机器人变敷衍了"，
     * 没有任何报错指向"协议校验从未生效"这个真因。
     * 排查成本极高，而且**不会自愈**。
     *
     * @throws IllegalStateException 有 schema 缺失或编译失败时抛出
     */
    public void assertSchemasLoadable() {
        List<String> missing = new ArrayList<>();
        for (String schemaName : REQUIRED_SCHEMA_NAMES) {
            if (loadSchema(schemaName) == null) {
                missing.add(schemaName);
            }
        }
        if (!missing.isEmpty()) {
            throw new IllegalStateException(
                    "协议 schema 加载不到：" + String.join(", ", missing)
                            + "。协议 schema 必须随应用一起分发（classpath 路径 "
                            + CLASSPATH_SCHEMA_ROOT
                            + "，或源码树中的 ../protocol/schema）。"
                            + "缺它会导致每条上行消息都被判为未知协议而丢弃。");
        }
    }

    /**
     * 读取并编译一份 schema。
     *
     * <p>按 classpath → 文件系统的顺序找：
     *
     * <ol>
     *   <li>classpath（jar 内）—— 部署形态的唯一可靠来源；
     *   <li>文件系统目录 —— 开发期从源码树直接跑的备用路径。
     * </ol>
     *
     * <p>classpath 优先是有意的：打成 jar 部署时，文件系统上那份可能是
     * **旧版本**（比如上一版源码），而 jar 里这份与本次构建严格一致。
     * 反过来做就会出现"改了 schema 但没重新打包，行为还是旧的"这种
     * 极难察觉的错位。
     *
     * @param schemaName schema 名
     * @return 编译后的 schema；找不到时返回 null
     */
    private JsonSchema readSchema(String schemaName) {
        String fileName = schemaName + ".schema.json";
        String content = readFromClasspath(fileName);
        if (content == null) {
            content = readFromDirectory(fileName);
        }
        if (content == null) {
            return null;
        }
        try {
            JsonSchemaFactory factory = buildSchemaFactory();
            SchemaValidatorsConfig config = SchemaValidatorsConfig.builder().build();
            return factory.getSchema(content, config);
        } catch (RuntimeException error) {
            throw new IllegalStateException("协议 schema 编译失败：" + fileName, error);
        }
    }

    /**
     * 从 classpath 读 schema 内容。
     *
     * @param fileName schema 文件名
     * @return 内容；classpath 里没有时返回 null
     */
    private String readFromClasspath(String fileName) {
        String resource = CLASSPATH_SCHEMA_ROOT + "/" + fileName;
        ClassLoader loader = ProtocolValidator.class.getClassLoader();
        try (InputStream stream = loader.getResourceAsStream(resource)) {
            if (stream == null) {
                return null;
            }
            return new String(stream.readAllBytes(), StandardCharsets.UTF_8);
        } catch (IOException error) {
            throw new UncheckedIOException("读取协议 schema 失败：" + resource, error);
        }
    }

    /**
     * 从文件系统目录读 schema 内容（开发期备用路径）。
     *
     * @param fileName schema 文件名
     * @return 内容；文件不存在时返回 null
     */
    private String readFromDirectory(String fileName) {
        Path schemaPath = schemaDirectory.resolve(fileName);
        if (!Files.exists(schemaPath)) {
            return null;
        }
        try {
            return Files.readString(schemaPath, StandardCharsets.UTF_8);
        } catch (IOException error) {
            throw new UncheckedIOException("读取协议 schema 失败：" + schemaPath, error);
        }
    }

    /**
     * 构建 schema 工厂。
     *
     * <p>协议 schema 之间存在相对引用（例如 {@code session.schema.json} 引用
     * {@code audio-negotiation.schema.json}）。默认行为是把这些相对引用当成
     * 远程 URL 去下载，既慢又会打网络。这里把协议域名映射到本地，
     * 让引用在本地解析。
     *
     * <p>映射目标的选择很重要：
     *
     * <ul>
     *   <li>classpath 里有 schema（部署形态）→ 映射到 classpath 目录的 URI，
     *       让 jar 内的引用能在 jar 内解析；
     *   <li>classpath 里没有（开发期）→ 映射到文件系统目录 URI。
     * </ul>
     *
     * <p>映射错了的后果很隐蔽：引用解析不到时，{@code $ref} 会被当成
     * 一个不受约束的普通字段，于是**校验反而"通过"了** ——
     * 看起来 schema 在起作用，实际引用的约束全丢了。
     *
     * @return schema 工厂
     */
    private JsonSchemaFactory buildSchemaFactory() {
        if (schemaOnClasspath()) {
            // ★ 部署形态：schema 在 jar 内。引用必须也能在 jar 内解析，
            //   所以映射到 classpath: 方案，并注册 ClasspathSchemaLoader。
            //
            //   为什么不能只用 mapPrefix 映射到 classpath 的 file: URI：
            //   jar 里的资源没有稳定的 file: 路径（jar URL 是
            //   jar:file:/...!/BOOT-INF/classes/...，不是文件系统路径），
            //   映射过去仍然读不到。
            return JsonSchemaFactory.getInstance(
                    VersionFlag.V202012,
                    builder -> builder
                            .schemaMappers(mappers -> mappers.mapPrefix(
                                    SCHEMA_URI_PREFIX, CLASSPATH_IRI_PREFIX))
                            .schemaLoaders(loaders -> loaders.add(new ClasspathSchemaLoader())));
        }
        // 开发期：schema 在源码树里，映射到目录 URI 让相对引用在本地解析。
        String localPrefix = schemaDirectory.toUri().toString();
        return JsonSchemaFactory.getInstance(
                VersionFlag.V202012,
                builder -> builder.schemaMappers(mappers -> mappers.mapPrefix(SCHEMA_URI_PREFIX, localPrefix)));
    }

    /**
     * 判断协议 schema 是否在 classpath 上（部署形态）。
     *
     * @return classpath 上有 schema 时返回 true
     */
    public boolean classpathHasSchemas() {
        ClassLoader loader = ProtocolValidator.class.getClassLoader();
        try (InputStream stream =
                loader.getResourceAsStream(CLASSPATH_SCHEMA_ROOT + "/session.schema.json")) {
            return stream != null;
        } catch (IOException error) {
            throw new UncheckedIOException("探测协议 schema classpath 失败", error);
        }
    }

    /**
     * 判断协议 schema 是否在 classpath 上（部署形态）。
     *
     * @return classpath 上有 schema 时返回 true
     */
    private boolean schemaOnClasspath() {
        return classpathHasSchemas();
    }

    private String describe(ValidationMessage message) {
        String instanceLocation = message.getInstanceLocation() == null
                ? ""
                : message.getInstanceLocation().toString();
        return "字段 " + (instanceLocation.isEmpty() ? "(根)" : instanceLocation) + "：" + message.getMessage();
    }
}
