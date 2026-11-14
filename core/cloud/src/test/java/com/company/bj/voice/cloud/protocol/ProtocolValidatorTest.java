package com.company.bj.voice.cloud.protocol;

import static org.assertj.core.api.Assertions.assertThat;

import java.nio.file.Path;
import java.util.List;
import org.junit.jupiter.api.Test;

class ProtocolValidatorTest {

    private static final Path SCHEMA_DIR = Path.of("..", "protocol", "schema");

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
}
