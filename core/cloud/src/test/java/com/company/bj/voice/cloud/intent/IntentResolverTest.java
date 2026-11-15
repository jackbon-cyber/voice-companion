package com.company.bj.voice.cloud.intent;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * {@link IntentResolver} 三级判定的行为测试。
 *
 * <p>用一个可计数的假分类器验证"端侧命中时不再调用云端模型"——
 * 这是三级判定存在的核心理由，必须有明确的调用次数断言。
 */
class IntentResolverTest {

    /** 可计数的假分类器。 */
    private static final class CountingClassifier implements IntentClassifier {
        private int calls;
        private final IntentClassifier.Classification result;

        CountingClassifier(IntentClassifier.Classification result) {
            this.result = result;
        }

        @Override
        public Classification classify(String text) {
            calls++;
            return result;
        }

        @Override
        public List<String> supportedIntents() {
            return List.of("stub");
        }
    }

    @Test
    @DisplayName("端侧高置信度判定时直接采信且不调用云端模型")
    void 端侧高置信度判定时直接采信且不调用云端模型() {
        CountingClassifier classifier = new CountingClassifier(
            IntentClassifier.Classification.of(IntentSamples.CHECK_TIME, 0.9));
        IntentResolver resolver = new IntentResolver(classifier);

        IntentResolution resolution = resolver.resolve(new IntentResolver.IntentRequest(
            "现在几点了",
            EdgeDecision.of(IntentSamples.CHECK_TIME, 0.85)));

        assertEquals(IntentSamples.CHECK_TIME, resolution.intent());
        assertEquals(IntentResolution.IntentSource.EDGE, resolution.source());
        assertEquals(0, classifier.calls, "端侧已确定时不应调用云端模型");
    }

    @Test
    @DisplayName("端侧置信度不足时改由云端模型判定")
    void 端侧置信度不足时改由云端模型判定() {
        CountingClassifier classifier = new CountingClassifier(
            IntentClassifier.Classification.of(IntentSamples.CHECK_TIME, 0.9));
        IntentResolver resolver = new IntentResolver(classifier);

        IntentResolution resolution = resolver.resolve(new IntentResolver.IntentRequest(
            "现在几点了",
            EdgeDecision.of(IntentSamples.CHECK_TIME, 0.3)));

        assertEquals(IntentResolution.IntentSource.CLOUD_MODEL, resolution.source());
        assertEquals(1, classifier.calls);
    }

    @Test
    @DisplayName("端侧未判定时由云端模型判定")
    void 端侧未判定时由云端模型判定() {
        CountingClassifier classifier = new CountingClassifier(
            IntentClassifier.Classification.of(IntentSamples.WEATHER_QUERY, 0.8));
        IntentResolver resolver = new IntentResolver(classifier);

        IntentResolution resolution = resolver.resolve(
            IntentResolver.IntentRequest.of("外面下雨吗"));

        assertEquals(IntentSamples.WEATHER_QUERY, resolution.intent());
        assertEquals(IntentResolution.IntentSource.CLOUD_MODEL, resolution.source());
        assertEquals(1, classifier.calls);
    }

    @Test
    @DisplayName("云端也无法判定时返回未知意图")
    void 云端也无法判定时返回未知意图() {
        CountingClassifier classifier = new CountingClassifier(
            IntentClassifier.Classification.of(IntentClassifier.UNKNOWN_INTENT, 0.2));
        IntentResolver resolver = new IntentResolver(classifier);

        IntentResolution resolution = resolver.resolve(
            IntentResolver.IntentRequest.of("嗯嗯嗯"));

        assertEquals(IntentClassifier.UNKNOWN_INTENT, resolution.intent());
        assertEquals(IntentResolution.IntentSource.UNKNOWN, resolution.source());
        assertFalse(resolution.resolved());
    }

    @Test
    @DisplayName("意图确定但缺必填槽位时进入澄清而非未知")
    void 意图确定但缺必填槽位时进入澄清而非未知() {
        CountingClassifier classifier = new CountingClassifier(
            IntentClassifier.Classification.of(IntentSamples.SET_VOLUME, 0.85));
        IntentResolver resolver = new IntentResolver(classifier);

        IntentResolution resolution = resolver.resolve(
            IntentResolver.IntentRequest.of("把声音调一下"));

        assertEquals(IntentSamples.SET_VOLUME, resolution.intent());
        assertTrue(resolution.resolved(), "意图已确定，不应被判为未知");
        assertTrue(resolution.needsClarification());
        assertEquals(List.of(SlotRequirements.SLOT_VOLUME_LEVEL), resolution.missingSlots());
    }

    @Test
    @DisplayName("必填槽位已填齐时不需要澄清")
    void 必填槽位已填齐时不需要澄清() {
        CountingClassifier classifier = new CountingClassifier(
            new IntentClassifier.Classification(
                IntentSamples.SET_VOLUME, 0.85, Map.of(SlotRequirements.SLOT_VOLUME_LEVEL, "50")));
        IntentResolver resolver = new IntentResolver(classifier);

        IntentResolution resolution = resolver.resolve(
            IntentResolver.IntentRequest.of("把音量调到五十"));

        assertTrue(resolution.resolved());
        assertFalse(resolution.needsClarification());
        assertEquals("50", resolution.slots().get(SlotRequirements.SLOT_VOLUME_LEVEL));
    }

    @Test
    @DisplayName("无必填槽位的意图不会被追问")
    void 无必填槽位的意图不会被追问() {
        CountingClassifier classifier = new CountingClassifier(
            IntentClassifier.Classification.of(IntentSamples.EMOTIONAL_SUPPORT, 0.85));
        IntentResolver resolver = new IntentResolver(classifier);

        IntentResolution resolution = resolver.resolve(
            IntentResolver.IntentRequest.of("我今天很难过"));

        assertFalse(resolution.needsClarification());
        assertTrue(resolution.missingSlots().isEmpty());
    }
}
