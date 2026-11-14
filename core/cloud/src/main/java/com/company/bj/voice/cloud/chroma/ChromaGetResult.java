package com.company.bj.voice.cloud.chroma;

import java.util.List;
import java.util.Map;

/**
 * 按 id 从 Chroma 集合读到的记录。
 *
 * <p>三个字段均为<b>一维</b>数组，对应 Chroma v2 {@code /get} 端点的原生形状，
 * 与 {@link ChromaQueryResult} 的二维结构不同，解析时不可混用。
 *
 * @param ids       记录 id
 * @param documents 文档文本
 * @param metadatas 元数据
 */
public record ChromaGetResult(
    List<String> ids,
    List<String> documents,
    List<Map<String, Object>> metadatas) {
}
