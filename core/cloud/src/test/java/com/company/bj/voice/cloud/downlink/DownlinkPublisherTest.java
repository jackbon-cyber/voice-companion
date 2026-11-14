package com.company.bj.voice.cloud.downlink;

import static org.assertj.core.api.Assertions.assertThat;

import com.company.bj.voice.cloud.protocol.ProtocolValidator;
import java.nio.file.Path;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class DownlinkPublisherTest {

    /** 协议 schema 所在目录。 */
    private static final Path SCHEMA_DIR = Path.of("..", "protocol", "schema");

    private DownlinkPublisher publisher;

    @BeforeEach
    void setUp() {
        publisher = new DownlinkPublisher(new ProtocolValidator(SCHEMA_DIR));
    }

    @Test
    void 首个语音片段带首包标记() {
        List<String> sent = publisher.publishVoice("s-1", List.of("AAA=", "BBB="));

        assertThat(sent).hasSize(2);
        assertThat(sent.get(0)).contains("\"isFirst\":true");
        assertThat(sent.get(1)).doesNotContain("\"isFirst\":true");
    }

    @Test
    void 末个语音片段带末包标记() {
        List<String> sent = publisher.publishVoice("s-1", List.of("AAA=", "BBB="));

        assertThat(sent.get(1)).contains("\"isLast\":true");
        assertThat(sent.get(0)).doesNotContain("\"isLast\":true");
    }

    @Test
    void 单片段同时带首包与末包标记() {
        List<String> sent = publisher.publishVoice("s-1", List.of("AAA="));

        assertThat(sent.get(0)).contains("\"isFirst\":true");
        assertThat(sent.get(0)).contains("\"isLast\":true");
    }

    @Test
    void 片段序号连续递增() {
        List<String> sent = publisher.publishVoice("s-1", List.of("A", "B", "C"));

        assertThat(sent.get(0)).contains("\"sequence\":0");
        assertThat(sent.get(1)).contains("\"sequence\":1");
        assertThat(sent.get(2)).contains("\"sequence\":2");
    }

    @Test
    void 语音片段符合协议() {
        List<String> sent = publisher.publishVoice("s-1", List.of("AAA=", "BBB="));

        for (String payload : sent) {
            assertThat(publisher.validateChunk(payload)).isEmpty();
        }
    }

    @Test
    void 文本回复符合协议() {
        String payload = publisher.publishText("s-1", "今天过得怎么样？", "tenderness");

        assertThat(publisher.validateText(payload)).isEmpty();
    }
    @Test
    void 文本回复带情感标签() {
        String payload = publisher.publishText("s-1", "别急，慢慢说", "tenderness");

        assertThat(payload).contains("\"emotion\":\"tenderness\"");
    }

    @Test
    void 文本回复可带引用来源() {
        String payload = publisher.publishText(
                "s-1", "你上次说你喜欢清淡的", "neutral", List.of("memory-1"));

        assertThat(payload).contains("\"citations\":[\"memory-1\"]");
    }

    @Test
    void 情感标签非法时报错() {
        try {
            publisher.publishText("s-1", "内容", "angry");
            throw new AssertionError("非法情感标签应当报错");
        } catch (IllegalArgumentException expected) {
            assertThat(expected.getMessage()).contains("emotion");
        }
    }

    @Test
    void 空回复文本报错() {
        try {
            publisher.publishText("s-1", "", "neutral");
            throw new AssertionError("空文本应当报错");
        } catch (IllegalArgumentException expected) {
            assertThat(expected.getMessage()).contains("text");
        }
    }

    @Test
    void 序号在不同发布之间连续递增() {
        publisher.publishVoice("s-1", List.of("AAA="));
        List<String> second = publisher.publishVoice("s-1", List.of("BBB="));

        assertThat(second.get(0)).contains("\"sequence\":1");
    }
}
