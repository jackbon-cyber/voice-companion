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
