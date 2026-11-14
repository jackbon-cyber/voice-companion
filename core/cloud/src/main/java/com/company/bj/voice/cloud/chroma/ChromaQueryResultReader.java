package com.company.bj.voice.cloud.chroma;

import java.util.List;
import java.util.Map;

/**
 * Chroma 检索结果解析器。
 *
 * <p>承担两件事：<b>结果解析</b>（把 Chroma 的二维响应读成扁平的命中序列）
 * 与<b>距离到得分的换算</b>。两个消费者 ——
 * {@code ChromaKnowledgeRetriever}（平台检索端口）与 {@code ChromaStore}
 * （AgentScope SPI 适配器）—— 都组合本类，因此行为完全一致。
 *
 * <p><b>得分公式在本类中只存在一份</b>。这一点是刻意的：
 * 公式若在两处各写一份，修复其中一处时另一处就会漂移，
 * 表现为"同一个查询在不同入口得到不同得分"这类极难定位的问题。
 *
 * <p><b>得分语义</b>：Chroma 的 {@code /query} 返回的距离是<b>平方</b> L2
 * （{@code sum((a_i - b_i)^2)}，已对 live Chroma 实测确认），
 * 本类按 {@code score = 1 / (1 + distance)} 换算，使得分<b>越大越相关</b>。
 *
 * <p>由于写入与查询两侧的向量都经过单位归一化，
 * 单位向量之间 {@code squared_L2 = 2 - 2·cos}，落在 {@code [0, 4]}，
 * 因此得分落在 {@code [0.2, 1.0]}，且与余弦相似度<b>单调对应</b>
 * （余弦越大 → 距离越小 → 得分越大）。
 */
public final class ChromaQueryResultReader {

    /** 相似度换算公式的常数项。 */
    private static final double SCORE_OFFSET = 1.0;

    private ChromaQueryResultReader() {
        throw new IllegalStateException("工具类不允许实例化");
    }

    /**
     * 返回检索结果第一行的长度，即本次查询的命中条数。
     *
     * <p>Chroma 的 {@code /query} 响应是二维数组，外层维度等于查询条数。
     * 本工程只发一条查询，因此取第一行；响应缺项时返回 0。
     *
     * @param result Chroma 检索结果
     * @return 命中条数
     */
    public static int hitCount(ChromaQueryResult result) {
        List<List<String>> ids = result.ids();
        if (ids == null || ids.isEmpty() || ids.get(0) == null) {
            return 0;
        }
        return ids.get(0).size();
    }

    /**
     * 读取第 i 条命中的记录 id。
     *
     * @param result Chroma 检索结果
     * @param index  命中下标
     * @return 记录 id，缺失时为 {@code null}
     */
    public static String idAt(ChromaQueryResult result, int index) {
        return result.ids().get(0).get(index);
    }

    /**
     * 读取第 i 条命中的正文。
     *
     * @param result Chroma 检索结果
     * @param index  命中下标
     * @return 正文，缺失时为空字符串
     */
    public static String documentAt(ChromaQueryResult result, int index) {
        List<List<String>> documents = result.documents();
        if (documents == null || documents.isEmpty() || documents.get(0) == null
            || index >= documents.get(0).size()) {
            return "";
        }
        String document = documents.get(0).get(index);
        return document == null ? "" : document;
    }

    /**
     * 读取第 i 条命中的元数据。
     *
     * @param result Chroma 检索结果
     * @param index  命中下标
     * @return 元数据，缺失时为空 Map
     */
    public static Map<String, Object> metadataAt(ChromaQueryResult result, int index) {
        List<List<Map<String, Object>>> metadatas = result.metadatas();
        if (metadatas == null || metadatas.isEmpty() || metadatas.get(0) == null
            || index >= metadatas.get(0).size()) {
            return Map.of();
        }
        Map<String, Object> metadata = metadatas.get(0).get(index);
        return metadata == null ? Map.of() : metadata;
    }

    /**
     * 读取第 i 条命中的距离。
     *
     * @param result Chroma 检索结果
     * @param index  命中下标
     * @return 距离，缺失时为 {@code null}
     */
    public static Double distanceAt(ChromaQueryResult result, int index) {
        List<List<Double>> distances = result.distances();
        if (distances == null || distances.isEmpty() || distances.get(0) == null
            || index >= distances.get(0).size()) {
            return null;
        }
        return distances.get(0).get(index);
    }

    /**
     * 把距离换算成相似度得分。
     *
     * <p>Chroma 默认空间为 L2 且返回的是<b>平方</b> L2 距离；
     * 本工程写入与查询两侧的向量都是单位向量，因此距离落在 {@code [0, 4]}，
     * 换算出的得分落在 {@code [0.2, 1.0]}，<b>越大越相关</b>，
     * 且与余弦相似度单调对应（{@code squared_L2 = 2 - 2·cos}）。
     *
     * @param distance 距离值，为 {@code null} 时视为完全不相关
     * @return 相似度得分
     */
    public static double toScore(Double distance) {
        if (distance == null) {
            return 0.0;
        }
        return SCORE_OFFSET / (SCORE_OFFSET + distance);
    }
}
