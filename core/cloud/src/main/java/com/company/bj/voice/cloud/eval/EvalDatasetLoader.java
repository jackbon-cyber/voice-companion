package com.company.bj.voice.cloud.eval;

import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 评测集加载器。
 *
 * <p>评测集以<b>纯文本</b>存储（{@code 维度|输入|期望} 每行一条），
 * 而不是 JSON 或 CSV。理由：
 * <ul>
 *   <li>纯文本可以被人直接读、被 diff、被手写补充 ——
 *       评测集的迭代频率很高，编辑门槛必须足够低；</li>
 *   <li>不用引号转义，中文内容里出现标点不会被搞乱；</li>
 *   <li>加载逻辑简单到不需要专门的解析框架。</li>
 * </ul>
 *
 * <p><b>评测集的唯一存放处是仓库根的 {@code core/eval/} 目录</b>，
 * Java（云端维度）与 Python（端侧维度）两个执行器读<b>同一份</b>文件。
 * 各写一份的后果很具体：两份会各自漂移，
 * 报告里的数字来自哪一份就说不清了。
 */
public class EvalDatasetLoader {

    /** 评测集在仓库中的相对路径。 */
    public static final String EVAL_DIR = "core/eval/";

    /** 评测集文件扩展名。 */
    public static final String FILE_SUFFIX = "-eval.txt";

    /** 工具类不允许实例化。 */
    private EvalDatasetLoader() {
        throw new UnsupportedOperationException("utility class");
    }

    /**
     * 从目录加载云端侧评测集。
     *
     * <p><b>只加载云端维度的文件</b>：端侧维度（如 ASR）由 Python 执行器评测，
     * 它的评测集格式与云端不同（需要噪声条件与音频合成），
     * 混进同一份解析器会让格式校验失去意义。
     *
     * @param evalDir 评测集目录
     * @return 评测集
     * @throws IOException 读取失败时抛出
     */
    public static EvalDataset loadFromDirectory(Path evalDir) throws IOException {
        List<EvalSample> samples = new ArrayList<>();
        if (!Files.isDirectory(evalDir)) {
            throw new IOException("评测集目录不存在：" + evalDir.toAbsolutePath());
        }
        try (var files = Files.list(evalDir)) {
            for (Path file : files.filter(path -> path.getFileName().toString()
                .endsWith(FILE_SUFFIX)).sorted().toList()) {
                EvalDimension dimension = dimensionOf(file);
                if (dimension.cloudSide()) {
                    samples.addAll(loadFile(file, dimension));
                }
            }
        }
        return new EvalDataset(samples);
    }

    /**
     * 从类路径加载某个维度的评测样本。
     *
     * @param classLoader 类加载器
     * @param dimension   评测维度
     * @return 样本列表
     * @throws IOException 读取失败时抛出
     */
    public static List<EvalSample> loadDimension(
        ClassLoader classLoader, EvalDimension dimension) throws IOException {

        String resource = EVAL_DIR + dimension.name().toLowerCase(java.util.Locale.ROOT)
            + FILE_SUFFIX;
        InputStream stream = classLoader.getResourceAsStream(resource);
        if (stream == null) {
            return List.of();
        }

        List<EvalSample> samples = new ArrayList<>();
        try (BufferedReader reader = new BufferedReader(
            new InputStreamReader(stream, StandardCharsets.UTF_8))) {

            String line;
            int lineNumber = 0;
            while ((line = reader.readLine()) != null) {
                lineNumber++;
                String trimmed = line.trim();
                if (trimmed.isEmpty() || trimmed.startsWith("#")) {
                    continue;
                }
                samples.add(parseLine(dimension, trimmed, resource, lineNumber));
            }
        }
        return samples;
    }

    /**
     * 加载一个评测集文件。
     *
     * @param file 文件路径
     * @return 样本列表
     * @throws IOException 读取或解析失败时抛出
     */
    public static List<EvalSample> loadFile(Path file) throws IOException {
        return loadFile(file, dimensionOf(file));
    }

    /**
     * 加载一个评测集文件。
     *
     * @param file      文件路径
     * @param dimension 评测维度
     * @return 样本列表
     * @throws IOException 读取或解析失败时抛出
     */
    public static List<EvalSample> loadFile(Path file, EvalDimension dimension) throws IOException {
        List<EvalSample> samples = new ArrayList<>();
        int lineNumber = 0;
        for (String line : Files.readAllLines(file, StandardCharsets.UTF_8)) {
            lineNumber++;
            String trimmed = line.trim();
            if (trimmed.isEmpty() || trimmed.startsWith("#")) {
                continue;
            }
            samples.add(parseLine(dimension, trimmed, file.toString(), lineNumber));
        }
        return samples;
    }

    /**
     * 从文件名推断评测维度。
     *
     * @param file 文件路径
     * @return 评测维度
     * @throws IOException 文件名无法识别时抛出
     */
    private static EvalDimension dimensionOf(Path file) throws IOException {
        String name = file.getFileName().toString();
        String stem = name.substring(0, name.length() - FILE_SUFFIX.length());
        for (EvalDimension dimension : EvalDimension.values()) {
            if (dimension.name().equalsIgnoreCase(stem.replace('-', '_'))) {
                return dimension;
            }
        }
        throw new IOException("评测集文件名无法识别维度：" + name);
    }

    /**
     * 解析一行评测样本。
     *
     * <p><b>支持三种格式</b>：
     * <ul>
     *   <li>{@code 维度|输入|期望} —— 三段，问句与记忆原文相同；</li>
     *   <li>{@code 维度|输入|期望|记忆原文} —— 四段，问句与记忆原文不同
     *       （记忆召回维度用它测语义召回）；</li>
     *   <li>{@code 维度|输入|期望|记忆原文|期望内容} —— 五段，
     *       最后一栏<b>留空</b>表示"库里没有这条记忆，期望系统拒答"。
     *       记忆作答维度用它区分"答不上"与"答错了"。</li>
     * </ul>
     *
     * @param dimension  评测维度
     * @param line       行内容
     * @param source     来源标识（用于错误提示）
     * @param lineNumber 行号
     * @return 评测样本
     * @throws IOException 格式错误时抛出
     */
    private static EvalSample parseLine(
        EvalDimension dimension, String line, String source, int lineNumber) throws IOException {

        String[] parts = line.split("\\|", -1);
        if (parts.length == 3) {
            return EvalSample.of(dimension, parts[1], parts[2]);
        }
        if (parts.length == 4) {
            return EvalSample.withCorpus(dimension, parts[1], parts[2], parts[3]);
        }
        if (parts.length == 5) {
            // 第五段留空 = 期望拒答（库里没有这条记忆）。
            // 注意第四段（记忆原文）在这种情况下也必须留空 ——
            // 否则这条样本会自己向记忆库写入一条记录，
            // "库里没有答案"的前提就被自己破坏了。
            String corpus = parts[3].isBlank() ? null : parts[3];
            String expectedContent = parts[4].isBlank() ? null : parts[4];
            if (corpus == null && expectedContent == null) {
                return EvalSample.expectingRefusal(dimension, parts[1], parts[2]);
            }
            return new EvalSample(dimension, parts[1], parts[2], corpus,
                expectedContent, Map.of());
        }
        throw new IOException("评测集格式错误：" + source + " 第 " + lineNumber
            + " 行，期望 3 段（维度|输入|期望）、4 段（维度|输入|期望|记忆原文）"
            + "或 5 段（维度|输入|期望|记忆原文|期望内容），实际 "
            + parts.length + " 段");
    }

    /**
     * 加载语料（用于交集检查）。
     *
     * @param classLoader 类加载器
     * @param resource    语料资源路径
     * @return 语料行列表
     * @throws IOException 读取失败时抛出
     */
    public static List<String> loadCorpus(ClassLoader classLoader, String resource)
        throws IOException {

        InputStream stream = classLoader.getResourceAsStream(resource);
        if (stream == null) {
            return List.of();
        }
        List<String> lines = new ArrayList<>();
        try (BufferedReader reader = new BufferedReader(
            new InputStreamReader(stream, StandardCharsets.UTF_8))) {

            String line;
            while ((line = reader.readLine()) != null) {
                String trimmed = line.trim();
                if (!trimmed.isEmpty() && !trimmed.startsWith("#")) {
                    lines.add(trimmed);
                }
            }
        }
        return lines;
    }
}
