package com.company.bj.voice.cloud.eval;

import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * 评测集。
 *
 * <p><b>关键性质：与训练/示例语料交集为空</b>（任务 10.1）。
 *
 * <p>这不是形式要求。如果评测集里混进了训练时见过的句子，
 * 那么测出来的准确率衡量的是<b>背诵能力</b>而不是<b>泛化能力</b> ——
 * 这个数字拿去求职演示，是自欺欺人。
 *
 * <p><b>交集检查按"归一化后完全相同"判定</b>，
 * 而不是按子串。子串太宽松（"放音乐" vs "放音乐吧" 会判为重叠，
 * 但它们其实是不同的表达），完全相同才可能是真的重复。
 */
public class EvalDataset {

    /** 评测样本。 */
    private final List<EvalSample> samples;

    /**
     * 构造评测集。
     *
     * @param samples 评测样本
     */
    public EvalDataset(List<EvalSample> samples) {
        this.samples = List.copyOf(samples);
    }

    /**
     * 返回全部样本。
     *
     * @return 样本列表
     */
    public List<EvalSample> samples() {
        return samples;
    }

    /**
     * 返回指定维度的样本。
     *
     * @param dimension 评测维度
     * @return 样本列表
     */
    public List<EvalSample> samplesOf(EvalDimension dimension) {
        return samples.stream()
            .filter(sample -> sample.dimension() == dimension)
            .toList();
    }

    /**
     * 检查评测集与语料的交集。
     *
     * @param corpus 训练/示例语料
     * @return 交集结果
     */
    public CorpusOverlap checkOverlap(List<String> corpus) {
        Set<String> normalizedCorpus = new LinkedHashSet<>();
        for (String line : corpus == null ? List.<String>of() : corpus) {
            normalizedCorpus.add(normalize(line));
        }

        Set<String> overlapping = new LinkedHashSet<>();
        for (EvalSample sample : samples) {
            String normalized = normalize(sample.input());
            if (normalizedCorpus.contains(normalized)) {
                overlapping.add(sample.input());
            }
        }

        return new CorpusOverlap(overlapping, normalizedCorpus.size());
    }

    /**
     * 检查<b>要求严格不相交的维度</b>与语料的交集。
     *
     * <p>意图与记忆召回两个维度靠<b>学习</b>产出结果，
     * 评测句与原型句或记忆原文重复就意味着在测背诵。
     * 安全与共情两个维度靠<b>词表规则</b>产出结果，
     * 评测样本本来就必须触发这些规则，因此不做此检查
     * （它们的重叠情况在报告中如实列出）。
     *
     * @param corpus 训练/示例语料
     * @return 交集结果
     */
    public CorpusOverlap checkStrictOverlap(List<String> corpus) {
        Set<String> normalizedCorpus = new LinkedHashSet<>();
        for (String line : corpus == null ? List.<String>of() : corpus) {
            normalizedCorpus.add(normalize(line));
        }

        Set<String> overlapping = new LinkedHashSet<>();
        for (EvalSample sample : samples) {
            if (!sample.dimension().requiresCorpusDisjoint()) {
                continue;
            }
            String normalized = normalize(sample.input());
            if (normalizedCorpus.contains(normalized)) {
                overlapping.add(sample.dimension().name() + ": " + sample.input());
            }
        }

        return new CorpusOverlap(overlapping, normalizedCorpus.size());
    }

    /**
     * 归一化文本，用于交集判定。
     *
     * @param text 原始文本
     * @return 归一化结果
     */
    private String normalize(String text) {
        if (text == null) {
            return "";
        }
        return text.replaceAll("[\\s，。！？、,.!?：:；;\"'“”‘’（）()【】]", "")
            .toLowerCase();
    }

    /**
     * 交集检查结果。
     *
     * @param overlapping 与语料重复的评测样本
     * @param corpusSize 语料条数
     */
    public record CorpusOverlap(Set<String> overlapping, int corpusSize) {

        /**
         * 判断交集是否为空。
         *
         * @return 交集为空返回 {@code true}
         */
        public boolean disjoint() {
            return overlapping.isEmpty();
        }
    }
}
