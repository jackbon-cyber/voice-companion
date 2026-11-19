package com.company.bj.voice.cloud.eval;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 评测执行器。
 *
 * <p>逐条执行评测样本，统计各维度的实测值，与 {@link EvalGates} 中的阈值比对，
 * 产出结构化报告。
 *
 * <p><b>报告必须包含四要素</b>（任务 10.3）：实测值、门禁阈值、样本规模、判定结论。
 * 缺任何一项，读者就无法判断这个数字是否可信 ——
 * "准确率 92%"单独拿出来既不知道样本量，也不知道及格线。
 */
public class EvalExecutor {

    /**
     * 非适用标记。
     *
     * <p>打分器返回这个值表示"这条样本<b>不适用本维度</b>，
     * 它既不算正确也不算错误"。
     *
     * <p><b>为什么需要它</b>：有些维度的"失败"有两种性质截然不同的形态 ——
     * 「做错了」与「没做」。记忆作答维度里，
     * "答错了记忆内容"是严重失败（用户被误导），
     * 而"没把握所以如实说没有记录"是<b>正确行为</b>。
     * 把两者混在一个分母里，会逼着打分器把拒答粉饰成作答 ——
     * 那才是真正的退步。
     *
     * <p>被标记为非适用的样本<b>既不进分子也不进分母</b>，
     * 因此"永远拒答"的系统不会因此拿到高分 ——
     * 它的准确率分母会变成 0，由
     * {@link #detectAllExcluded} 显式拦下来。
     */
    public static final String NON_APPLICABLE = "NON_APPLICABLE";

    /** 评测执行器。 */
    private final EvalDataset dataset;

    /**
     * 构造评测执行器。
     *
     * @param dataset 评测集
     */
    public EvalExecutor(EvalDataset dataset) {
        this.dataset = dataset;
    }

    /**
     * 执行某个维度的评测。
     *
     * @param dimension 评测维度
     * @param scorer    打分器
     * @return 维度结果
     */
    public DimensionResult evaluate(EvalDimension dimension, Scorer scorer) {
        List<EvalSample> samples = dataset.samplesOf(dimension);

        if (samples.isEmpty()) {
            return DimensionResult.empty(dimension, "该维度没有评测样本，不参与门禁判定");
        }

        int correct = 0;
        int applicable = 0;
        int excluded = 0;
        List<String> failures = new ArrayList<>();
        // 打分只做一次并把结果留在这里：记忆召回的打分器有写副作用
        // （把样本写进长期记忆），重复调用会把同一条样本写多遍。
        List<String> actuals = new ArrayList<>(samples.size());
        for (EvalSample sample : samples) {
            String actual = scorer.score(sample);
            actuals.add(actual);
            if (NON_APPLICABLE.equals(actual)) {
                excluded++;
                continue;
            }
            applicable++;
            if (actual != null && actual.equals(sample.expected())) {
                correct++;
            } else {
                failures.add("输入=" + sample.input()
                    + " 期望=" + sample.expected() + " 实际=" + actual);
            }
        }

        // 全部样本都被排除时，分母为 0，比率无意义 ——
        // 这通常意味着打分器的口径写错了（比如把"没把握"一律当成不适用）。
        // 必须显式拦下来，否则会算出 NaN 或 1.0 之类的假数字。
        String allExcluded = detectAllExcluded(samples.size(), excluded);
        if (allExcluded != null) {
            return DimensionResult.empty(dimension, allExcluded);
        }

        // 打分器与期望值若不在同一套词汇里（如打分器返回 "MATCH" 而期望值是
        // "blocked"），上面的比较会**全部判失败**。这种失败看起来像"指标不达标"，
        // 实则是打分器写错了 —— 必须显式拦下来，否则排查方向会被带偏。
        String vocabularyMismatch = detectVocabularyMismatch(samples, actuals, scorer);
        if (vocabularyMismatch != null) {
            return DimensionResult.empty(dimension, vocabularyMismatch);
        }

        double rate = (double) correct / applicable;
        Double threshold = thresholdOf(dimension);
        Boolean passed = null;
        String conclusion;

        if (threshold == null) {
            conclusion = "该维度无门禁阈值，仅记录实测值";
        } else if (applicable < EvalGates.MIN_SAMPLE_SIZE) {
            passed = null;
            conclusion = "适用样本数 " + applicable + " 少于最小样本数 "
                + EvalGates.MIN_SAMPLE_SIZE + "，不参与门禁判定";
        } else {
            passed = rate >= threshold;
            conclusion = (passed
                ? "实测 " + format(rate) + " ≥ 阈值 " + format(threshold) + "，通过"
                : "实测 " + format(rate) + " < 阈值 " + format(threshold) + "，不通过")
                + "（适用样本 " + applicable + " 条，不适用 " + excluded + " 条）";
        }

        return new DimensionResult(dimension, applicable, rate, threshold, passed,
            conclusion, failures, excluded);
    }

    /**
     * 检测全部样本都被排除的情形。
     *
     * @param total   样本总数
     * @param excluded 被排除的样本数
     * @return 说明文本；不存在该问题时返回 {@code null}
     */
    private String detectAllExcluded(int total, int excluded) {
        if (total == 0 || excluded < total) {
            return null;
        }
        return "全部 " + total + " 条样本都被判定为不适用，本维度无有效样本，"
            + "不参与门禁判定";
    }

    /**
     * 检测打分器返回值与期望值是否属于同一套词汇。
     *
     * <p>判据：打分器的返回值必须落在<b>合法词汇集合</b>内。
     * 合法词汇集合 = 评测集期望值出现过的取值 ∪ 打分器自行声明的取值。
     *
     * <p><b>为什么要并上打分器声明的取值</b>：
     * 只看期望值时，"模型全错"会被误判成"打分器写错了"——
     * 指标越差越容易绕过门禁，这是最危险的漏洞形态。
     * 记忆作答维度就踩过这个坑：期望值只有 {@code ANSWERED}，
     * 而打分器合法地会产出 {@code WRONG}。
     *
     * <p><b>为什么必须显式拦截</b>：词汇不一致时的实测值会是 0，
     * 报告上写着"准确率 0%，不达标"，排查的人会以为是模型不行，
     * 而真实原因是打分器写错了。这个误判方向的代价太高。
     *
     * @param samples 评测样本
     * @param actuals 打分器的实际返回值
     * @param scorer  打分器
     * @return 词汇不一致时的说明；一致时返回 {@code null}
     */
    private String detectVocabularyMismatch(List<EvalSample> samples, List<String> actuals,
        Scorer scorer) {

        java.util.Set<String> legal = new java.util.LinkedHashSet<>();
        for (EvalSample sample : samples) {
            legal.add(sample.expected());
        }
        legal.addAll(scorer.vocabulary());

        int inVocabulary = 0;
        for (String actual : actuals) {
            if (actual != null && legal.contains(actual)) {
                inVocabulary++;
            }
        }

        if (inVocabulary > 0) {
            return null;
        }
        return "打分器返回值与评测集期望值不属于同一套词汇"
            + "（合法取值：" + legal + "），本维度结果不可信，不参与门禁判定";
    }

    /**
     * 取出某维度的门禁阈值。
     *
     * @param dimension 评测维度
     * @return 阈值；该维度无阈值时返回 {@code null}
     */
    public Double thresholdOf(EvalDimension dimension) {
        return switch (dimension) {
            case INTENT -> EvalGates.MIN_INTENT_ACCURACY;
            case MEMORY_RECALL -> EvalGates.MIN_MEMORY_RECALL;
            case MEMORY_ANSWER -> EvalGates.MIN_MEMORY_ANSWER;
            case ASR -> EvalGates.MIN_ASR_ACCURACY;
            case SAFETY -> EvalGates.MIN_SAFETY_RECALL;
            case EMPATHY -> EvalGates.MIN_EMPATHY_RATE;
        };
    }

    /**
     * 汇总多个维度的结果为报告。
     *
     * @param results 各维度结果
     * @return 评测报告
     */
    public EvalReport report(List<DimensionResult> results) {
        boolean overallPassed = results.stream()
            .allMatch(result -> result.passed() == null || result.passed());

        int failedDimensions = (int) results.stream()
            .filter(result -> Boolean.FALSE.equals(result.passed()))
            .count();

        return new EvalReport(results, overallPassed, failedDimensions);
    }

    /**
     * 格式化比率。
     *
     * @param value 比率值
     * @return 百分比文本
     */
    private String format(double value) {
        return String.format("%.1f%%", value * 100);
    }

    /**
     * 打分器端口。
     *
     * <p>把"怎么判对错"从执行器里抽出来：不同维度用完全不同的判据
     * （意图看标签是否匹配、记忆看召回到没有、安全看是否拦下）。
     */
    @FunctionalInterface
    public interface Scorer {

        /**
         * 对一条样本打分，返回实际结果。
         *
         * @param sample 评测样本
         * @return 实际结果；无法判定时返回 {@code null}
         */
        String score(EvalSample sample);

        /**
         * 返回本打分器可能产出的<b>全部</b>结果词。
         *
         * <p><b>为什么需要它</b>：判定"打分器与评测集是不是在说同一套话"时，
         * 只看期望值是不够的 —— 像记忆作答维度，期望值只有 {@code ANSWERED}，
         * 但打分器合法地会产出 {@code WRONG}（答错了）与
         * {@code NON_APPLICABLE}（如实拒答）。
         *
         * <p>若把"没命中期望值"一律当成"词汇不一致"，
         * 那么<b>模型全错时反而会被判成"打分器写错了，不参与门禁判定"</b> ——
         * 这是最危险的一种门禁漏洞：指标越差，越容易绕过门禁。
         *
         * <p>默认返回空集合，表示"本打分器只产出期望值里出现过的词"。
         *
         * @return 结果词集合
         */
        default java.util.Set<String> vocabulary() {
            return java.util.Set.of();
        }
    }

    /**
     * 单维度评测结果。
     *
     * @param dimension 评测维度
     * @param sampleSize 适用样本数（不含被判定为不适用的样本）
     * @param rate      实测比率
     * @param threshold 门禁阈值；无阈值时为空
     * @param passed    是否通过；不参与判定时为空
     * @param conclusion 判定结论
     * @param failures  失败样本明细
     * @param excludedCount 被判定为不适用的样本数
     */
    public record DimensionResult(
        EvalDimension dimension,
        int sampleSize,
        double rate,
        Double threshold,
        Boolean passed,
        String conclusion,
        List<String> failures,
        int excludedCount) {

        /**
         * 构造一个"无样本"的结果。
         *
         * @param dimension 评测维度
         * @param conclusion 判定结论
         * @return 维度结果
         */
        public static DimensionResult empty(EvalDimension dimension, String conclusion) {
            return new DimensionResult(dimension, 0, 0.0, null, null, conclusion, List.of(), 0);
        }

        /**
         * 返回样本总数（适用样本 + 不适用样本）。
         *
         * @return 样本总数
         */
        public int totalSampleSize() {
            return sampleSize + excludedCount;
        }
    }

    /**
     * 评测报告。
     *
     * @param results          各维度结果
     * @param overallPassed    总体是否通过
     * @param failedDimensions 不通过的维度数
     */
    public record EvalReport(
        List<DimensionResult> results, boolean overallPassed, int failedDimensions) {

        /**
         * 转为可序列化的映射，便于输出为 JSON。
         *
         * @return 报告内容
         */
        public Map<String, Object> toMap() {
            Map<String, Object> map = new LinkedHashMap<>();
            map.put("overallPassed", overallPassed);
            map.put("failedDimensions", failedDimensions);
            List<Map<String, Object>> dimensions = new ArrayList<>();
            for (DimensionResult result : results) {
                Map<String, Object> dimension = new LinkedHashMap<>();
                dimension.put("dimension", result.dimension().name());
                dimension.put("metric", result.dimension().metricName());
                dimension.put("sampleSize", result.sampleSize());
                dimension.put("excludedCount", result.excludedCount());
                dimension.put("measured", result.rate());
                dimension.put("threshold", result.threshold());
                dimension.put("passed", result.passed());
                dimension.put("conclusion", result.conclusion());
                dimension.put("failures", result.failures());
                dimensions.add(dimension);
            }
            map.put("dimensions", dimensions);
            return map;
        }
    }
}
