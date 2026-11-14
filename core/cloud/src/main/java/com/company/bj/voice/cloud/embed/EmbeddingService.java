package com.company.bj.voice.cloud.embed;

import java.util.List;

/**
 * 文本嵌入服务扩展点。
 *
 * <p>把文本转换为向量是知识库摄取与检索的共同前置步骤，抽象成接口后，
 * 调用方（摄取管线、检索端口、查询向量缓存）只依赖本契约，
 * 具体的模型服务与协议细节由实现类承载。
 */
public interface EmbeddingService {

    /**
     * 批量计算文本的嵌入向量。
     *
     * @param texts 待嵌入的文本列表
     * @return 与入参等长、顺序一一对应的向量列表
     * @throws EmbeddingException 凭据缺失、模型服务不可用、响应格式异常或维度不符时抛出
     */
    List<double[]> embed(List<String> texts);

    /**
     * 计算单条文本的嵌入向量。
     *
     * @param text 待嵌入的文本
     * @return 嵌入向量
     * @throws EmbeddingException 凭据缺失、模型服务不可用、响应格式异常或维度不符时抛出
     */
    default double[] embed(String text) {
        List<double[]> vectors = embed(List.of(text));
        if (vectors.isEmpty()) {
            throw new EmbeddingException("embedding returned no vector for the requested text");
        }
        return vectors.get(0);
    }
}
