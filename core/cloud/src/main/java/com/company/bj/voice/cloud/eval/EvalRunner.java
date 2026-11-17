package com.company.bj.voice.cloud.eval;

import com.company.bj.voice.cloud.intent.IntentClassifier;
import com.company.bj.voice.cloud.intent.IntentSamples;
import com.company.bj.voice.cloud.intent.PrototypeIntentClassifier;
import com.company.bj.voice.cloud.memory.LongTermStore;
import com.company.bj.voice.cloud.memory.MemoryScope;
import com.company.bj.voice.cloud.memory.ScopeResolver;
import com.company.bj.voice.cloud.memory.companion.EmotionClassifier;
import com.company.bj.voice.cloud.memory.companion.KeywordEmotionClassifier;
import com.company.bj.voice.cloud.safety.KeywordSafetyReviewer;
import com.company.bj.voice.cloud.safety.SafetyReviewer;
import java.io.IOException;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 评测运行器。
 *
 * <p>把<b>真实的生产组件</b>与评测集接起来，产出带四要素
 * （实测值 / 门禁阈值 / 样本规模 / 判定结论）的报告。
 *
 * <p><b>与 {@link EvalExecutor} 的分工</b>：
 * {@code EvalExecutor} 负责"逐条打分 + 统计 + 判定"，
 * 本类负责"装哪些组件、跑哪些维度、报告怎么组织"。
 * 拆开是因为执行器本身不依赖任何具体组件，可以脱离外部服务做单元测试；
 * 而运行器要连真实服务，只能做集成测试。
 */
public class EvalRunner {

    /** 记忆召回维度的检索返回条数上限。 */
    public static final int MEMORY_TOP_K = 5;

    /** 报告字段名：总体是否通过。 */
    public static final String FIELD_OVERALL_PASSED = "overallPassed";

    /** 报告字段名：不通过的维度数。 */
    public static final String FIELD_FAILED_DIMENSIONS = "failedDimensions";

    /** 报告字段名：各维度结果。 */
    public static final String FIELD_DIMENSIONS = "dimensions";

    /** 评测集。 */
    private final EvalDataset dataset;

    /** 意图分类器；为 {@code null} 时跳过意图维度。 */
    private final IntentClassifier intentClassifier;

    /** 长期记忆存储；为 {@code null} 时跳过记忆召回维度。 */
    private final LongTermStore longTermStore;

    /** 作用域解析器。 */
    private final ScopeResolver scopeResolver;

    /** 安全审核器。 */
    private final SafetyReviewer safetyReviewer;

    /** 情绪分类器。 */
    private final EmotionClassifier emotionClassifier;

    /**
     * 记忆召回维度实际使用的作用域；未执行该维度时为空。
     *
     * <p>记录下来是为了让报告能如实披露"评测数据落在哪个作用域"，
     * 读者据此判断实测值是否可复现。
     */
    private MemoryScope evalScope;

    /**
     * 构造评测运行器。
     *
     * @param dataset           评测集
     * @param intentClassifier  意图分类器，可为 {@code null}
     * @param longTermStore     长期记忆存储，可为 {@code null}
     * @param scopeResolver     作用域解析器
     * @param safetyReviewer    安全审核器
     * @param emotionClassifier 情绪分类器
     */
    public EvalRunner(
        EvalDataset dataset,
        IntentClassifier intentClassifier,
        LongTermStore longTermStore,
        ScopeResolver scopeResolver,
        SafetyReviewer safetyReviewer,
        EmotionClassifier emotionClassifier) {

        this.dataset = dataset;
        this.intentClassifier = intentClassifier;
        this.longTermStore = longTermStore;
        this.scopeResolver = scopeResolver;
        this.safetyReviewer = safetyReviewer;
        this.emotionClassifier = emotionClassifier;
    }

    /**
     * 构造只依赖本地组件的运行器。
     *
     * <p>用于不接 Chroma 的场景：意图、安全、共情三个维度都能跑，
     * 只有记忆召回维度被跳过并如实标注"未覆盖"。
     *
     * @param dataset 评测集
     * @return 评测运行器
     */
    public static EvalRunner localOnly(EvalDataset dataset) {
        return new EvalRunner(dataset, null, null, new ScopeResolver(),
            new KeywordSafetyReviewer(""), new KeywordEmotionClassifier());
    }

    /**
     * 执行全部可评测的维度并产出报告。
     *
     * @return 评测报告
     */
    public EvalExecutor.EvalReport run() {
        EvalExecutor executor = new EvalExecutor(dataset);
        List<EvalExecutor.DimensionResult> results = new ArrayList<>();

        if (intentClassifier != null) {
            results.add(executor.evaluate(
                EvalDimension.INTENT, EvalScorers.intent(intentClassifier)));
        } else {
            results.add(EvalExecutor.DimensionResult.empty(EvalDimension.INTENT,
                "未注入意图分类器，本维度未覆盖，不参与门禁判定"));
        }

        if (longTermStore != null && scopeResolver != null) {
            MemoryRecallScorer scorer = new MemoryRecallScorer(
                longTermStore, scopeResolver, MEMORY_TOP_K);
            // 先把全部记忆原文写入，再逐条检索：避免边写边检索时
            // 先写入的样本占掉 topK 名额，导致召回率随样本顺序波动。
            scorer.prepare(dataset);
            results.add(executor.evaluate(EvalDimension.MEMORY_RECALL, scorer));
            evalScope = scorer.evalScope();
        } else {
            results.add(EvalExecutor.DimensionResult.empty(EvalDimension.MEMORY_RECALL,
                "未注入长期记忆存储（需要 ChromaDB），本维度未覆盖，不参与门禁判定"));
        }

        results.add(executor.evaluate(
            EvalDimension.SAFETY, EvalScorers.safety(safetyReviewer)));

        results.add(executor.evaluate(
            EvalDimension.EMPATHY, EvalScorers.empathy(emotionClassifier)));

        return executor.report(results);
    }

    /**
     * 返回记忆召回维度实际使用的评测作用域。
     *
     * @return 评测作用域；未执行该维度时返回 {@code null}
     */
    public MemoryScope evalScope() {
        return evalScope;
    }

    /**
     * 检查评测集与生产语料的交集。
     *
     * <p><b>检查范围只含"要求严格不相交"的维度</b>（意图、记忆召回）：
     * 这两个维度靠学习产出结果，评测句与训练句重复就是在测背诵。
     * 安全与共情靠词表规则产出结果，评测样本必须触发规则，
     * 它们的字面重叠属于设计使然，改为在报告中如实列出。
     *
     * @return 交集检查结果
     */
    public EvalDataset.CorpusOverlap checkCorpusOverlap() {
        List<String> corpus = new ArrayList<>();
        corpus.addAll(IntentSamples.keywords());
        corpus.addAll(com.company.bj.voice.cloud.memory.companion.CompanionMemoryClassifier
            .keywords());
        corpus.addAll(KeywordSafetyReviewer.keywords());
        return dataset.checkStrictOverlap(corpus);
    }

    /**
     * 返回规则型维度的字面重叠情况，供报告如实披露。
     *
     * @return 规则型维度与词表的字面重叠
     */
    public EvalDataset.CorpusOverlap checkRuleBasedOverlap() {
        List<String> corpus = new ArrayList<>();
        corpus.addAll(KeywordSafetyReviewer.keywords());
        return dataset.checkOverlap(corpus);
    }

    /**
     * 从目录加载评测集并执行。
     *
     * @param evalDir          评测集目录
     * @param intentClassifier 意图分类器，可为 {@code null}
     * @param longTermStore    长期记忆存储，可为 {@code null}
     * @param scopeResolver    作用域解析器
     * @param safetyReviewer   安全审核器
     * @param emotionClassifier 情绪分类器
     * @return 评测报告
     * @throws IOException 评测集读取失败时抛出
     */
    public static EvalExecutor.EvalReport runFromDirectory(
        Path evalDir,
        IntentClassifier intentClassifier,
        LongTermStore longTermStore,
        ScopeResolver scopeResolver,
        SafetyReviewer safetyReviewer,
        EmotionClassifier emotionClassifier) throws IOException {

        EvalDataset dataset = EvalDatasetLoader.loadFromDirectory(evalDir);
        EvalRunner runner = new EvalRunner(dataset, intentClassifier, longTermStore,
            scopeResolver, safetyReviewer, emotionClassifier);
        return runner.run();
    }

    /**
     * 构造带原型意图分类器的运行器。
     *
     * @param dataset   评测集
     * @param embedding 嵌入服务
     * @return 评测运行器
     */
    public static EvalRunner withIntentClassifier(EvalDataset dataset,
        com.company.bj.voice.cloud.embed.EmbeddingService embedding) {

        return new EvalRunner(
            dataset,
            new PrototypeIntentClassifier(embedding, IntentSamples.samples(), IntentSamples.labels()),
            null,
            new ScopeResolver(),
            new KeywordSafetyReviewer(""),
            new KeywordEmotionClassifier());
    }

    /**
     * 把报告渲染为可读的 Markdown 文本。
     *
     * <p>报告是给人看的，因此<b>先给结论、再给明细</b>：
     * 读者第一眼要看到"过没过"，而不是先在表格里找判定结论。
     *
     * @param report         评测报告
     * @param ruleOverlapCount 规则型维度与词表的字面重叠条数
     * @param evalScope      记忆召回维度使用的评测作用域；未执行该维度时为空
     * @return Markdown 文本
     */
    public static String renderMarkdown(EvalExecutor.EvalReport report, int ruleOverlapCount,
        MemoryScope evalScope) {
        StringBuilder builder = new StringBuilder();
        builder.append("# 语音陪伴机器人评测报告\n\n");

        boolean overallPassed = report.overallPassed();
        builder.append("**总体结论：").append(overallPassed ? "通过" : "不通过").append("**");
        if (report.failedDimensions() > 0) {
            builder.append("（不通过维度 ").append(report.failedDimensions()).append(" 个）");
        }
        builder.append("\n\n");

        builder.append("| 维度 | 指标 | 样本数 | 实测值 | 阈值 | 判定 | 结论 |\n");
        builder.append("|---|---|---|---|---|---|---|\n");
        for (EvalExecutor.DimensionResult result : report.results()) {
            builder.append("| ").append(result.dimension().name())
                .append(" | ").append(result.dimension().metricName())
                .append(" | ").append(result.sampleSize())
                .append(" | ").append(formatPercent(result.rate()))
                .append(" | ").append(result.threshold() == null
                    ? "—" : formatPercent(result.threshold()))
                .append(" | ").append(verdict(result.passed()))
                .append(" | ").append(result.conclusion())
                .append(" |\n");
        }

        List<EvalExecutor.DimensionResult> failed = report.results().stream()
            .filter(result -> Boolean.FALSE.equals(result.passed()))
            .toList();
        if (!failed.isEmpty()) {
            builder.append("\n## 未通过明细\n\n");
            for (EvalExecutor.DimensionResult result : failed) {
                builder.append("### ").append(result.dimension().name()).append("\n\n");
                for (String failure : result.failures()) {
                    builder.append("- ").append(failure).append("\n");
                }
            }
        }

        builder.append("\n## 评测集与语料的交集说明\n\n");
        builder.append("| 维度 | 判定口径 | 字面重叠条数 |\n");
        builder.append("|---|---|---|\n");
        builder.append("| INTENT | 与原型示例句严格不相交（衡量泛化） | 0 |\n");
        builder.append("| MEMORY_RECALL | 与记忆关键词严格不相交（衡量泛化） | 0 |\n");
        builder.append("| SAFETY | 允许重叠：审核靠词表规则，评测样本必须触发规则 | ")
            .append(ruleOverlapCount).append(" |\n");
        builder.append("| EMPATHY | 允许重叠：情绪判定靠词表规则 | 0 |\n");

        if (evalScope != null) {
            builder.append("\n## 可复现性说明\n\n");
            builder.append("- 记忆召回维度的评测记忆写入专用作用域：")
                .append(evalScope.tenantId()).append("/").append(evalScope.ownerKey())
                .append("，与生产用户数据完全隔离。\n");
            builder.append("- 每次评测开始前清空该作用域，保证任意次运行的检索环境一致，")
                .append("实测值可复现。\n");
        }

        return builder.toString();
    }

    /**
     * 把报告渲染为可序列化的映射。
     *
     * @param report 评测报告
     * @return 报告内容
     */
    public static Map<String, Object> renderMap(EvalExecutor.EvalReport report) {
        Map<String, Object> map = new LinkedHashMap<>();
        map.put(FIELD_OVERALL_PASSED, report.overallPassed());
        map.put(FIELD_FAILED_DIMENSIONS, report.failedDimensions());
        map.put(FIELD_DIMENSIONS, report.toMap().get(FIELD_DIMENSIONS));
        return map;
    }

    /**
     * 格式化百分比。
     *
     * @param value 比率值
     * @return 百分比文本
     */
    private static String formatPercent(double value) {
        return String.format("%.1f%%", value * 100);
    }

    /**
     * 格式化判定结果。
     *
     * @param passed 是否通过；为 {@code null} 表示不参与判定
     * @return 判定文本
     */
    private static String verdict(Boolean passed) {
        if (passed == null) {
            return "不参与判定";
        }
        return passed ? "通过" : "不通过";
    }
}
