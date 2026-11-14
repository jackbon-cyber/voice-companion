package com.company.bj.voice.cloud.chroma;

import java.util.List;
import java.util.Map;

/**
 * Chroma 向量检索结果。
 *
 * <p>四个字段均为<b>二维</b>数组：外层维度等于查询条数，内层为该条查询的命中结果。
 * 这是 Chroma v2 {@code /query} 端点的原生形状，与 {@link ChromaGetResult} 的一维数组不同。
 *
 * @param ids       命中记录 id
 * @param documents 命中文档文本
 * @param metadatas 命中元数据
 * @param distances 命中距离
 */
public record ChromaQueryResult(
    List<List<String>> ids,
    List<List<String>> documents,
    List<List<Map<String, Object>>> metadatas,
    List<List<Double>> distances) {
}
