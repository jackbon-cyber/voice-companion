package com.company.bj.voice.cloud.embed;

/**
 * 嵌入向量的单位归一化。
 *
 * <p><b>为什么必须归一化</b>：Chroma 的 {@code /query} 返回的距离是<b>平方</b> L2
 * （{@code sum((a_i - b_i)^2)}，已对 live Chroma 实测确认：探针向量与自身的
 * 平方 L2 为 {@code 0.0001}，真实 L2 为 {@code 0.01}）。
 * 本工程把距离按 {@code score = 1 / (1 + distance)} 换算成相似度，
 * 因此距离的尺度直接决定得分的尺度。
 *
 * <p>若向量未归一化，平方 L2 会随向量模长与维度急剧膨胀：
 * 实测中等模长的 1024 维向量之间距离已达 4~7，得分跌到 0.12~0.20，
 * "语义相近"与"语义无关"的结果得分几乎无法区分，相似度下限形同虚设。
 * 归一化后距离只取决于<b>方向</b>，得分才有稳定语义。
 *
 * <p><b>归一化后的距离与余弦的关系</b>：单位向量之间
 * {@code squared_L2 = |a|^2 + |b|^2 - 2·a·b = 2 - 2·cos}，
 * 因此 {@code score = 1 / (1 + squared_L2)} 与余弦相似度<b>单调对应</b>
 * （余弦越大、距离越小、得分越大），得分落在 {@code [0.2, 1.0]}。
 *
 * <p><b>零向量</b>：模长为 0 时无法归一化（除零会产生 NaN，
 * 进而污染下游距离计算），此时<b>原样返回零向量</b>。
 * 零向量与任意向量的平方 L2 等于对方模长的平方，得分是确定值，不会产生 NaN。
 */
public final class EmbeddingNormalizer {

    /** 浮点比较容差：用于判定模长是否已经为单位长度。 */
    public static final double UNIT_TOLERANCE = 1e-9;

    private EmbeddingNormalizer() {
        throw new IllegalStateException("工具类不允许实例化");
    }

    /**
     * 把向量归一化到单位长度。
     *
     * <p>零向量原样返回（不做除法），避免产生 NaN。
     *
     * @param vector 待归一化的向量，不可为 {@code null}
     * @return 单位长度的向量；输入为零向量时原样返回零向量
     */
    public static double[] normalize(double[] vector) {
        double norm = norm(vector);
        if (norm == 0.0) {
            return vector;
        }
        double[] normalized = new double[vector.length];
        for (int i = 0; i < vector.length; i++) {
            normalized[i] = vector[i] / norm;
        }
        return normalized;
    }

    /**
     * 计算向量的模长（欧几里得范数）。
     *
     * @param vector 向量
     * @return 模长
     */
    public static double norm(double[] vector) {
        double sumOfSquares = 0.0;
        for (double component : vector) {
            sumOfSquares += component * component;
        }
        return Math.sqrt(sumOfSquares);
    }

    /**
     * 判断向量的模长是否为单位长度（在浮点容差内）。
     *
     * @param vector 向量
     * @return 模长是否接近 1
     */
    public static boolean isUnitLength(double[] vector) {
        return Math.abs(norm(vector) - 1.0) <= UNIT_TOLERANCE;
    }
}
