package com.company.bj.voice.cloud.protocol;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Path;
import java.util.List;
import java.util.stream.Stream;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;

class ProtocolValidatorTest {

    private static final Path SCHEMA_DIR = Path.of("..", "protocol", "schema");

    private static final ObjectMapper MAPPER = new ObjectMapper();

    @Test
    void 合法音频帧通过校验() {
        ProtocolValidator validator = new ProtocolValidator(SCHEMA_DIR);
        List<String> errors = validator.validate("audio-frame",
                "{\"sessionId\":\"s1\",\"sequence\":0,\"timestampMs\":0,\"sampleRate\":16000,\"payloadBase64\":\"AAA=\"}");
        assertThat(errors).isEmpty();
    }

    @Test
    void 缺少必填字段时给出字段名() {
        ProtocolValidator validator = new ProtocolValidator(SCHEMA_DIR);
        List<String> errors = validator.validate("audio-frame", "{\"sequence\":0}");
        assertThat(errors).isNotEmpty();
        assertThat(errors.get(0)).contains("sessionId");
    }

    @Test
    void 未知schema名给出明确错误() {
        ProtocolValidator validator = new ProtocolValidator(SCHEMA_DIR);
        List<String> errors = validator.validate("not-exist", "{}");
        assertThat(errors).isNotEmpty();
        assertThat(errors.get(0)).contains("not-exist");
    }

    @Test
    void 非法JSON给出明确错误() {
        ProtocolValidator validator = new ProtocolValidator(SCHEMA_DIR);
        List<String> errors = validator.validate("audio-frame", "{not json");
        assertThat(errors).isNotEmpty();
    }

    /**
     * 守住"打成 jar 部署后协议 schema 仍可用"这条线。
     *
     * <p>★ 这个缺陷曾真实发生：协议 schema 住在 {@code core/protocol/schema/}，
     * 不在 cloud 模块内，没被打进 jar。部署后每条上行消息都被判
     * "未知协议 schema"而丢弃，而云端退回降级话术继续对话 ——
     * 现象只是"机器人变敷衍了"，没有任何报错指向真因。
     *
     * <p>本测试用**指向不存在目录**的 schemaDirectory 复现"只能靠 classpath"的场景：
     * 如果实现退回到读文件系统，本测试会失败。
     */
    @Test
    void schema只存在于classpath时仍能校验() {
        ProtocolValidator validator = new ProtocolValidator(Path.of("no-such-schema-dir"));
        List<String> errors = validator.validate("audio-frame",
                "{\"sessionId\":\"s1\",\"sequence\":0,\"timestampMs\":0,\"sampleRate\":16000,\"payloadBase64\":\"AAA=\"}");
        assertThat(errors).isEmpty();
    }

    /**
     * 守住跨 schema 的 {@code $ref} 引用在 classpath 形态下能解析。
     *
     * <p>{@code session.schema.json} 的 {@code audioFormat} 引用
     * {@code audio-negotiation.schema.json}。引用解析不到时，
     * {@code $ref} 会被当成一个不受约束的普通字段 ——
     * **校验反而"通过"了**，看起来 schema 在起作用，实际约束全丢了。
     *
     * <p>所以这里用一个**违反被引用 schema 约束**的载荷来验证：
     * 只有引用真的解析并生效了，才会报错。
     */
    @Test
    void 跨schema引用在classpath形态下仍然生效() {
        ProtocolValidator validator = new ProtocolValidator(Path.of("no-such-schema-dir"));
        // audioFormat 缺 sampleRate 等必填项 —— 违反 audio-negotiation.schema.json
        List<String> errors = validator.validate("session",
                "{\"sessionId\":\"s1\",\"type\":\"begin\",\"ownerKey\":\"u1\","
                        + "\"timestampMs\":0,\"audioFormat\":{\"sampleRate\":\"不是数字\"}}");
        assertThat(errors).isNotEmpty();
    }

    /**
     * 守住启动期自检：schema 缺失必须让启动失败，而不是静默降级。
     */
    @Test
    void schema缺失时启动自检必须失败() {
        ProtocolValidator validator = new ProtocolValidator(Path.of("no-such-schema-dir"));
        if (validator.classpathHasSchemas()) {
            // classpath 上有 schema（测试运行时会打进 target/classes）→ 自检应通过
            org.junit.jupiter.api.Assertions.assertDoesNotThrow(validator::assertSchemasLoadable);
            return;
        }
        org.junit.jupiter.api.Assertions.assertThrows(
                IllegalStateException.class, validator::assertSchemasLoadable);
    }

    @ParameterizedTest
    @MethodSource("protocolSamples")
    void 与Python侧对同一组样例的判定一致(Sample sample) {
        ProtocolValidator validator = new ProtocolValidator(SCHEMA_DIR);
        List<String> errors = validator.validate(sample.schema(), sample.payload());
        assertThat(errors.isEmpty()).as(sample.note()).isEqualTo(sample.valid());
    }

    static Stream<Arguments> protocolSamples() {
        return loadSamples().stream()
                .map(sample -> Arguments.of(sample));
    }

    /**
     * 读取与 Python 侧共享的协议样例。
     *
     * <p>样例文件只存在一份（{@code src/test/resources/protocol-samples/samples.json}），
     * Python 侧从仓库根目录按相对路径读同一份文件。
     *
     * @return 样例列表
     */
    static List<Sample> loadSamples() {
        try (InputStream stream = ProtocolValidatorTest.class
                .getResourceAsStream("/protocol-samples/samples.json")) {
            if (stream == null) {
                throw new IllegalStateException("共享样例文件缺失：/protocol-samples/samples.json");
            }
            JsonNode root = MAPPER.readTree(stream);
            return java.util.stream.StreamSupport.stream(root.get("samples").spliterator(), false)
                    .map(node -> new Sample(
                            node.get("schema").asText(),
                            node.get("valid").asBoolean(),
                            node.get("note").asText(),
                            node.get("payload").toString()))
                    .toList();
        } catch (IOException error) {
            throw new IllegalStateException("读取共享样例文件失败", error);
        }
    }

    /**
     * 一条协议样例。
     *
     * @param schema schema 名
     * @param valid 期望的判定结果
     * @param note 样例说明
     * @param payload 消息载荷（JSON 文本）
     */
    record Sample(String schema, boolean valid, String note, String payload) {
    }
}
