package com.company.bj.voice.cloud.eval;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.company.bj.voice.cloud.intent.IntentSamples;
import com.company.bj.voice.cloud.memory.companion.CompanionMemoryClassifier;
import com.company.bj.voice.cloud.safety.KeywordSafetyReviewer;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;

/**
 * 第 10 组评测集与执行器的行为测试。
 *
 * <p>核心断言：<b>评测集与语料交集为空</b>、<b>报告含四要素</b>、
 * <b>样本不足时不参与门禁</b>。
 */
class EvalDatasetTest {

    /** 评测集。 */
    private static EvalDataset dataset;

    /** 加载器使用的类加载器。 */
    private static ClassLoader loader = EvalDatasetTest.class.getClassLoader();

    /**
     * 定位仓库根目录下的评测集目录。
     *
     * <p>测试的工作目录是模块目录（{@code core/cloud}），
     * 评测集在仓库根的 {@code core/eval/}，因此要向上两级。
     *
     * @return 评测集目录
     */
    private static Path evalDirectory() {
        Path current = Path.of("").toAbsolutePath();
        for (int level = 0; level < 4; level++) {
            Path candidate = current.resolve("core").resolve("eval");
            if (Files.isDirectory(candidate)) {
                return candidate;
            }
            current = current.getParent();
        }
        throw new IllegalStateException("找不到评测集目录 core/eval");
    }

    @BeforeAll
    static void loadDataset() throws IOException {
        dataset = EvalDatasetLoader.loadFromDirectory(evalDirectory());
    }

    @Test
    @DisplayName("云端侧四个维度都有评测样本")
    void 云端侧四个维度都有评测样本() {
        for (EvalDimension dimension : EvalDimension.values()) {
            if (!dimension.cloudSide()) {
                continue;
            }
            assertFalse(dataset.samplesOf(dimension).isEmpty(),
                dimension + " 维度没有评测样本");
        }
    }

    @Test
    @DisplayName("端侧维度不在云端评测集内")
    void 端侧维度不在云端评测集内() {
        // ASR 由 Python 端侧评测器执行，格式不同（需要噪声条件与音频合成）
        assertTrue(dataset.samplesOf(EvalDimension.ASR).isEmpty(),
            "ASR 维度不应进入云端评测集");
    }

    @Test
    @DisplayName("五个维度的评测集文件都存在")
    void 五个维度的评测集文件都存在() {
        Path directory = evalDirectory();
        for (EvalDimension dimension : EvalDimension.values()) {
            Path file = directory.resolve(
                dimension.name().toLowerCase(java.util.Locale.ROOT) + "-eval.txt");
            assertTrue(Files.exists(file), "缺少评测集文件：" + file.getFileName());
        }
    }

    @Test
    @DisplayName("评测集与意图示例语料交集为空")
    void 评测集与意图示例语料交集为空() {
        // 直接引用生产代码里的示例句库 —— 若把语料抄一份在测试里，
        // 语料一改这份拷贝就会过期，交集检查形同虚设。
        List<String> corpus = new java.util.ArrayList<>();
        IntentSamples.samples().values().forEach(corpus::addAll);

        EvalDataset.CorpusOverlap overlap = dataset.checkOverlap(corpus);

        assertTrue(overlap.disjoint(),
            "评测集与语料存在交集：" + overlap.overlapping());
    }

    @Test
    @DisplayName("评测集与记忆分类关键词交集为空")
    void 评测集与记忆分类关键词交集为空() {
        List<String> corpus = CompanionMemoryClassifier.keywords();

        EvalDataset.CorpusOverlap overlap = dataset.checkOverlap(corpus);

        assertTrue(overlap.disjoint(), "交集：" + overlap.overlapping());
    }

    @Test
    @DisplayName("严格不相交的维度与安全审核关键词交集为空")
    void 严格不相交的维度与安全审核关键词交集为空() {
        List<String> corpus = KeywordSafetyReviewer.keywords();

        EvalDataset.CorpusOverlap overlap = dataset.checkStrictOverlap(corpus);

        assertTrue(overlap.disjoint(), "交集：" + overlap.overlapping());
    }

    @Test
    @DisplayName("安全维度与词表的重叠是设计使然，不得据此判失败")
    void 安全维度与词表的重叠是设计使然() {
        // 安全审核靠词表规则产出结果，评测样本<b>本来就必须触发这些规则</b> ——
        // 造出一堆规则覆盖不到的句子，测出来的召回率与真实能力无关。
        // 因此"评测集与安全词表字面重叠"是预期行为而不是数据泄漏；
        // 评测集加载器据此只对要求严格不相交的维度（意图、记忆召回）做交集检查。
        List<String> corpus = KeywordSafetyReviewer.keywords();

        EvalDataset.CorpusOverlap overlap = dataset.checkStrictOverlap(corpus);

        assertTrue(overlap.disjoint(),
            "严格不相交的维度不得与安全词表重叠：" + overlap.overlapping());
        assertFalse(EvalDimension.SAFETY.requiresCorpusDisjoint(),
            "安全维度不应要求严格不相交");
        assertTrue(EvalDimension.INTENT.requiresCorpusDisjoint(),
            "意图维度靠学习产出结果，必须要求严格不相交");
    }

    @Test
    @DisplayName("报告包含实测值/阈值/样本规模/结论四要素")
    void 报告包含实测值阈值样本规模结论四要素() {
        EvalExecutor executor = new EvalExecutor(dataset);

        EvalExecutor.DimensionResult result = executor.evaluate(
            EvalDimension.INTENT, sample -> sample.expected());

        assertTrue(result.sampleSize() > 0, "缺少样本规模");
        assertNotNull(result.threshold(), "缺少门禁阈值");
        assertTrue(result.rate() >= 0, "缺少实测值");
        assertFalse(result.conclusion().isBlank(), "缺少判定结论");
    }

    @Test
    @DisplayName("样本不足时不参与门禁判定")
    void 样本不足时不参与门禁判定() {
        EvalDataset tiny = new EvalDataset(List.of(
            EvalSample.of(EvalDimension.INTENT, "放歌", "play_music"),
            EvalSample.of(EvalDimension.INTENT, "报时", "check_time")));

        EvalExecutor executor = new EvalExecutor(tiny);
        EvalExecutor.DimensionResult result = executor.evaluate(
            EvalDimension.INTENT, sample -> sample.expected());

        assertEquals(null, result.passed(), "样本不足时应为不参与判定");
        assertTrue(result.conclusion().contains("不参与门禁判定"), result.conclusion());
    }

    @Test
    @DisplayName("实测值低于阈值时判定不通过")
    void 实测值低于阈值时判定不通过() {
        EvalDataset datasetUnderTest = new EvalDataset(List.of(
            EvalSample.of(EvalDimension.INTENT, "a", "x"),
            EvalSample.of(EvalDimension.INTENT, "b", "y"),
            EvalSample.of(EvalDimension.INTENT, "c", "z"),
            EvalSample.of(EvalDimension.INTENT, "d", "w"),
            EvalSample.of(EvalDimension.INTENT, "e", "v"),
            EvalSample.of(EvalDimension.INTENT, "f", "u"),
            EvalSample.of(EvalDimension.INTENT, "g", "t"),
            EvalSample.of(EvalDimension.INTENT, "h", "s"),
            EvalSample.of(EvalDimension.INTENT, "i", "r"),
            EvalSample.of(EvalDimension.INTENT, "j", "q"),
            EvalSample.of(EvalDimension.INTENT, "k", "p")));

        EvalExecutor executor = new EvalExecutor(datasetUnderTest);
        // 全部答错，但返回值必须落在期望值的取值集合内。
        // 若打分器返回的是一个期望值里根本没出现过的词（例如 "wrong"），
        // 执行器会判定为"打分器与评测集不在同一套词汇"并拒绝参与门禁 ——
        // 那种情况下报"准确率 0%"会把排查方向带偏（真实原因是打分器写错了）。
        // 这里返回最后一个期望值对应的标签：它落在词汇集合内（不被拦截），
        // 但只对一条样本成立，因此准确率为 1/11，仍然低于阈值。
        EvalExecutor.DimensionResult result = executor.evaluate(
            EvalDimension.INTENT, sample -> "p");

        assertEquals(Boolean.FALSE, result.passed());
        assertEquals(10, result.failures().size(),
            "11 条样本中只有 1 条被判对，其余 10 条应记为失败明细");
    }

    @Test
    @DisplayName("总体结论汇总各维度")
    void 总体结论汇总各维度() {
        EvalExecutor executor = new EvalExecutor(dataset);

        EvalExecutor.EvalReport report = executor.report(List.of(
            executor.evaluate(EvalDimension.INTENT, sample -> sample.expected()),
            executor.evaluate(EvalDimension.SAFETY, sample -> sample.expected())));

        assertNotNull(report.toMap().get("dimensions"));
        assertTrue(report.toMap().containsKey("overallPassed"));
    }

    @Test
    @DisplayName("门禁阈值与 EvalGates 一致")
    void 门禁阈值与EvalGates一致() {
        EvalExecutor executor = new EvalExecutor(dataset);

        assertEquals(EvalGates.MIN_INTENT_ACCURACY, executor.thresholdOf(EvalDimension.INTENT));
        assertEquals(EvalGates.MIN_MEMORY_RECALL, executor.thresholdOf(EvalDimension.MEMORY_RECALL));
        assertEquals(EvalGates.MIN_ASR_ACCURACY, executor.thresholdOf(EvalDimension.ASR));
        assertEquals(EvalGates.MIN_SAFETY_RECALL, executor.thresholdOf(EvalDimension.SAFETY));
        assertEquals(EvalGates.MIN_EMPATHY_RATE, executor.thresholdOf(EvalDimension.EMPATHY));
    }
}
