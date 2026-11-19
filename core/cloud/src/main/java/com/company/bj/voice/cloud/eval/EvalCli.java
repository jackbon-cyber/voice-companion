package com.company.bj.voice.cloud.eval;

import com.company.bj.voice.cloud.chroma.ChromaClient;
import com.company.bj.voice.cloud.config.ChromaProperties;
import com.company.bj.voice.cloud.embed.EmbeddingService;
import com.company.bj.voice.cloud.embed.LocalEmbeddingService;
import com.company.bj.voice.cloud.intent.IntentClassifier;
import com.company.bj.voice.cloud.intent.IntentSamples;
import com.company.bj.voice.cloud.intent.PrototypeIntentClassifier;
import com.company.bj.voice.cloud.memory.ChromaLongTermStore;
import com.company.bj.voice.cloud.memory.LongTermStore;
import com.company.bj.voice.cloud.memory.MemoryScope;
import com.company.bj.voice.cloud.memory.ScopeResolver;
import com.company.bj.voice.cloud.memory.companion.KeywordEmotionClassifier;
import com.company.bj.voice.cloud.safety.KeywordSafetyReviewer;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.net.http.HttpClient;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 评测命令行入口。
 *
 * <p><b>为什么单独做一个 CLI 而不是只写单元测试</b>：
 * 门禁的产出必须是一份<b>能给人看、也能给 CI 判退出码</b>的报告，
 * 而不是测试日志里的一行断言。
 *
 * <p><b>退出码约定</b>（脚本据此分流，避免"脚本失败了但不知道为什么"）：
 * <ul>
 *   <li>{@code 0} —— 全部维度通过，或未覆盖的维度不参与判定；</li>
 *   <li>{@code 1} —— 有维度未达门禁阈值；</li>
 *   <li>{@code 2} —— 评测环境不可用（依赖服务没起、模型缺失）；</li>
 *   <li>{@code 3} —— 自检失败（评测集格式错、语料交集非空）。</li>
 * </ul>
 *
 * <p><b>依赖不可用时必须以 2 退出，而不是降级为 0</b>：
 * 把"没跑"报成"通过"是最危险的一种失败 —— 它会让门禁形同虚设。
 */
public final class EvalCli {

    /** 退出码：全部通过。 */
    public static final int EXIT_PASSED = 0;

    /** 退出码：有维度不达标。 */
    public static final int EXIT_GATE_FAILED = 1;

    /** 退出码：环境不可用。 */
    public static final int EXIT_ENV_UNAVAILABLE = 2;

    /** 退出码：自检失败。 */
    public static final int EXIT_SELF_CHECK_FAILED = 3;

    /** 评测集目录相对路径（相对仓库根）。 */
    public static final String DEFAULT_EVAL_DIR = "core/eval";

    /** 报告输出路径相对路径（相对仓库根）。 */
    public static final String DEFAULT_REPORT_PATH = "core/eval-report.md";

    /** JSON 报告输出路径相对路径（相对仓库根）。 */
    public static final String DEFAULT_JSON_REPORT_PATH = "core/eval-report.json";

    /** 本地嵌入服务基址。 */
    private static final String DEFAULT_EMBEDDING_BASE_URL = "http://127.0.0.1:8766";

    /** ChromaDB 基址。与云端 {@code application.yml} 的默认配置一致。 */
    private static final String DEFAULT_CHROMA_BASE_URL = "http://127.0.0.1:8765";

    /** 工具类不允许实例化。 */
    private EvalCli() {
        throw new UnsupportedOperationException("utility class");
    }

    /**
     * 命令行入口。
     *
     * @param args 命令行参数
     */
    public static void main(String[] args) {
        System.exit(run(args));
    }

    /**
     * 执行评测。
     *
     * @param args 命令行参数
     * @return 进程退出码
     */
    public static int run(String[] args) {
        Options options = Options.parse(args);
        if (options.selfCheck()) {
            return selfCheck(options);
        }
        return execute(options);
    }

    /**
     * 执行自检模式。
     *
     * <p><b>自检不连接任何依赖服务</b>：它只检查评测集格式与语料交集。
     * 这样自检可以在任何机器上跑，包括 CI 的隔离容器。
     *
     * @param options 命令行选项
     * @return 进程退出码
     */
    private static int selfCheck(Options options) {
        try {
            EvalDataset dataset = EvalDatasetLoader.loadFromDirectory(options.evalDir());
            EvalRunner runner = EvalRunner.localOnly(dataset);

            EvalDataset.CorpusOverlap overlap = runner.checkCorpusOverlap();
            if (!overlap.disjoint()) {
                System.err.println("自检失败：评测集与生产语料存在交集：" + overlap.overlapping());
                System.err.println("意图/记忆召回维度靠学习产出结果，评测句与训练句重复就是在测背诵。");
                return EXIT_SELF_CHECK_FAILED;
            }

            for (var dimension : EvalDimension.values()) {
                if (!dimension.cloudSide()) {
                    continue;
                }
                int count = dataset.samplesOf(dimension).size();
                if (count == 0) {
                    System.err.println("自检失败：" + dimension + " 维度没有评测样本");
                    return EXIT_SELF_CHECK_FAILED;
                }
                System.out.println("自检通过：" + dimension + " 维度 " + count + " 条样本");
            }

            System.out.println("自检通过：评测集与生产语料交集为空");
            return EXIT_PASSED;
        } catch (IOException error) {
            System.err.println("自检失败：评测集读取失败 —— " + error.getMessage());
            return EXIT_SELF_CHECK_FAILED;
        }
    }

    /**
     * 执行完整评测。
     *
     * @param options 命令行选项
     * @return 进程退出码
     */
    private static int execute(Options options) {
        EvalDataset dataset;
        try {
            dataset = EvalDatasetLoader.loadFromDirectory(options.evalDir());
        } catch (IOException error) {
            System.err.println("评测集读取失败：" + error.getMessage());
            return EXIT_SELF_CHECK_FAILED;
        }

        EvalRunner runner = EvalRunner.localOnly(dataset);
        EvalDataset.CorpusOverlap overlap = runner.checkCorpusOverlap();
        if (!overlap.disjoint()) {
            System.err.println("评测中止：评测集与生产语料存在交集：" + overlap.overlapping());
            return EXIT_SELF_CHECK_FAILED;
        }

        // 意图维度需要嵌入服务（本地 ONNX）。缺失时该维度标为未覆盖，不静默通过。
        IntentClassifier intentClassifier = null;
        try {
            EmbeddingService embeddings = new LocalEmbeddingService(
                embeddingProperties(options.embeddingBaseUrl()));
            intentClassifier = new PrototypeIntentClassifier(
                embeddings, IntentSamples.samples(), IntentSamples.labels());
            // 先探一次：嵌入服务不可用时不要等到评测中途才失败。
            intentClassifier.classify("测试");
        } catch (RuntimeException error) {
            System.err.println("意图维度不可用（本地嵌入服务未就绪）：" + error.getMessage());
            System.err.println("该维度将标记为未覆盖，不参与门禁判定。");
        }

        // 记忆召回维度需要 ChromaDB + 嵌入服务。缺失时该维度标为未覆盖，不静默通过。
        LongTermStore longTermStore = null;
        ScopeResolver scopeResolver = new ScopeResolver();
        try {
            EmbeddingService embeddings = new LocalEmbeddingService(
                embeddingProperties(options.embeddingBaseUrl()));
            LongTermStore store = buildLongTermStore(
                embeddings, options.chromaBaseUrl(), scopeResolver);
            // 先探一次：Chroma 不可用时不要等到评测中途才失败。
            // 探测用评测作用域，与后续打分的作用域一致，避免探到生产数据。
            scopeResolver.withScopeResult(
                MemoryScope.of(MemoryRecallScorer.EVAL_TENANT_ID,
                    MemoryRecallScorer.EVAL_OWNER_KEY), () -> {
                    store.list(1);
                    return null;
                });
            longTermStore = store;
        } catch (RuntimeException error) {
            System.err.println("记忆召回维度不可用（ChromaDB 或嵌入服务未就绪）：" + error.getMessage());
            System.err.println("该维度将标记为未覆盖，不参与门禁判定。");
            longTermStore = null;
        }

        EvalRunner wiredRunner = new EvalRunner(dataset, intentClassifier, longTermStore,
            scopeResolver, new KeywordSafetyReviewer(""), new KeywordEmotionClassifier());

        EvalExecutor.EvalReport report = wiredRunner.run();
        int ruleOverlapCount = wiredRunner.checkRuleBasedOverlap().overlapping().size();
        EvalEnvironment environment = collectEnvironment(options);
        String markdown = EvalRunner.renderMarkdown(report, ruleOverlapCount,
            wiredRunner.evalScope(), environment,
            new EvalRunner.AnswerRateSummary(
                wiredRunner.memoryAnswerRate(), wiredRunner.answerRatePassed(),
                wiredRunner.fabricationRate(), wiredRunner.fabricationPassed()));
        String json = renderJson(report, environment, wiredRunner.memoryAnswerRate(),
            wiredRunner.answerRatePassed(), wiredRunner.fabricationRate(),
            wiredRunner.fabricationPassed());

        try {
            writeReport(options.reportPath(), markdown);
            writeReport(options.jsonReportPath(), json);
        } catch (IOException error) {
            System.err.println("报告写入失败：" + error.getMessage());
            return EXIT_ENV_UNAVAILABLE;
        }

        System.out.println(markdown);
        System.out.println("报告已写入：" + options.reportPath());
        System.out.println("JSON 报告已写入：" + options.jsonReportPath());

        return report.overallPassed() ? EXIT_PASSED : EXIT_GATE_FAILED;
    }

    /**
     * 构造基于 ChromaDB 的长期记忆存储。
     *
     * <p><b>作用域解析器必须与调用方共用同一个实例</b>：
     * 存储层从解析器读作用域，写入方通过解析器设置作用域。
     * 两者不是同一个实例时，存储层永远读不到作用域，表现为
     * {@code no active memory scope}。
     *
     * @param embeddings    嵌入服务
     * @param chromaBaseUrl ChromaDB 基址
     * @param scopeResolver 作用域解析器
     * @return 长期记忆存储
     */
    private static LongTermStore buildLongTermStore(
        EmbeddingService embeddings, String chromaBaseUrl, ScopeResolver scopeResolver) {

        ChromaProperties chromaProperties = new ChromaProperties();
        chromaProperties.setBaseUrl(chromaBaseUrl);

        ChromaClient chroma = new ChromaClient(
            chromaProperties,
            HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).build(),
            new ObjectMapper());

        return new ChromaLongTermStore(chroma, embeddings, chromaProperties, scopeResolver);
    }

    /**
     * 采集评测环境信息。
     *
     * <p><b>只采集稳定标识，绝不采集时间戳</b>：报告要能被两次运行的 diff 比对，
     * 带生成时间的报告每次必然不同，真实指标的变化会被噪声淹没。
     *
     * <p>某个组件探测失败时不中断评测 —— 环境信息是补充说明，
     * 不是判据。此时该条目留空，由使用者自己判断这次结果的可比性。
     *
     * @param options 命令行选项
     * @return 环境信息
     */
    private static EvalEnvironment collectEnvironment(Options options) {
        Map<String, String> entries = new LinkedHashMap<>(4);
        entries.put("jdk", System.getProperty("java.version", "未知"));
        entries.put("chroma", probeChromaVersion(options.chromaBaseUrl()));
        entries.put("embedding", options.embeddingBaseUrl());
        return new EvalEnvironment(entries);
    }

    /**
     * 探测 ChromaDB 版本号。
     *
     * @param chromaBaseUrl ChromaDB 基址
     * @return 版本号；探测失败时返回说明文本而非抛异常
     */
    private static String probeChromaVersion(String chromaBaseUrl) {
        try {
            ChromaProperties props = new ChromaProperties();
            props.setBaseUrl(chromaBaseUrl);
            ChromaClient chroma = new ChromaClient(props,
                HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(3)).build(),
                new ObjectMapper());
            return chroma.version();
        } catch (RuntimeException error) {
            return "不可用（" + error.getMessage() + "）";
        }
    }

    /**
     * 渲染 JSON 报告。
     *
     * @param report      评测报告
     * @param environment 评测环境信息
     * @param answerRate  记忆作答维度的作答率
     * @return JSON 文本
     */
    private static String renderJson(EvalExecutor.EvalReport report, EvalEnvironment environment,
        double answerRate, Boolean answerRatePassed, double fabricationRate,
        Boolean fabricationPassed) {
        try {
            ObjectMapper mapper = new ObjectMapper();
            return mapper.writerWithDefaultPrettyPrinter().writeValueAsString(
                EvalRunner.renderMap(report, environment, answerRate, answerRatePassed,
                    fabricationRate, fabricationPassed));
        } catch (IOException error) {
            return "{\"error\":\"" + error.getMessage() + "\"}";
        }
    }

    /**
     * 写入报告文件。
     *
     * @param path     文件路径
     * @param content  文件内容
     * @throws IOException 写入失败时抛出
     */
    private static void writeReport(Path path, String content) throws IOException {
        Path parent = path.toAbsolutePath().getParent();
        if (parent != null) {
            Files.createDirectories(parent);
        }
        Files.writeString(path, content, StandardCharsets.UTF_8);
    }

    /**
     * 构造嵌入配置。
     *
     * @param baseUrl 本地嵌入服务基址
     * @return 嵌入配置
     */
    private static com.company.bj.voice.cloud.config.EmbeddingProperties embeddingProperties(
        String baseUrl) {

        com.company.bj.voice.cloud.config.EmbeddingProperties props =
            new com.company.bj.voice.cloud.config.EmbeddingProperties();
        props.setLocalEmbeddingBaseUrl(baseUrl);
        return props;
    }

    /**
     * 命令行选项。
     *
     * @param evalDir        评测集目录
     * @param reportPath     Markdown 报告输出路径
     * @param jsonReportPath JSON 报告输出路径
     * @param embeddingBaseUrl 本地嵌入服务基址
     * @param chromaBaseUrl  ChromaDB 基址
     * @param selfCheck      是否只做自检
     */
    public record Options(
        Path evalDir,
        Path reportPath,
        Path jsonReportPath,
        String embeddingBaseUrl,
        String chromaBaseUrl,
        boolean selfCheck) {

        /**
         * 解析命令行参数。
         *
         * @param args 命令行参数
         * @return 解析后的选项
         */
        public static Options parse(String[] args) {
            Path evalDir = Path.of(DEFAULT_EVAL_DIR);
            Path reportPath = Path.of(DEFAULT_REPORT_PATH);
            Path jsonReportPath = Path.of(DEFAULT_JSON_REPORT_PATH);
            String embeddingBaseUrl = DEFAULT_EMBEDDING_BASE_URL;
            String chromaBaseUrl = DEFAULT_CHROMA_BASE_URL;
            boolean selfCheck = false;

            for (int index = 0; index < args.length; index++) {
                switch (args[index]) {
                    case "--eval-dir" -> evalDir = Path.of(requireValue(args, ++index, "--eval-dir"));
                    case "--report" -> reportPath = Path.of(requireValue(args, ++index, "--report"));
                    case "--json-report" ->
                        jsonReportPath = Path.of(requireValue(args, ++index, "--json-report"));
                    case "--embedding-url" ->
                        embeddingBaseUrl = requireValue(args, ++index, "--embedding-url");
                    case "--chroma-url" ->
                        chromaBaseUrl = requireValue(args, ++index, "--chroma-url");
                    case "--self-check" -> selfCheck = true;
                    default -> throw new IllegalArgumentException("未知参数：" + args[index]);
                }
            }

            return new Options(evalDir, reportPath, jsonReportPath, embeddingBaseUrl,
                chromaBaseUrl, selfCheck);
        }

        /**
         * 取出参数值。
         *
         * @param args  参数数组
         * @param index 值所在下标
         * @param name  参数名，用于错误提示
         * @return 参数值
         * @throws IllegalArgumentException 缺少值时抛出
         */
        private static String requireValue(String[] args, int index, String name) {
            if (index >= args.length) {
                throw new IllegalArgumentException("参数 " + name + " 缺少取值");
            }
            return args[index];
        }
    }
}
