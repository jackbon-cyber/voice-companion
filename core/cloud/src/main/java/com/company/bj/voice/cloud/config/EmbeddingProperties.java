package com.company.bj.voice.cloud.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 文本嵌入模型相关配置。
 *
 * <p><b>本工程默认走本地嵌入服务</b>（{@link #localEmbeddingBaseUrl}），
 * 而不是远端 OpenAI 兼容接口。理由：远端接口需要 API 凭据，
 * 而"克隆下来就能跑"是本作品面向求职场景的第一目标。
 * 本地嵌入服务由 {@code core/edge/embedding} 下的 ONNX 推理进程提供，
 * 模型为量化后的 BGE-small-zh（512 维，22.9 MB），完全离线可用。
 *
 * <p>远端接口保留为可选路径：有凭据时可切换到语义更强的模型，
 * 届时的向量维度必须同步调整（{@link #dimensions}）。
 *
 * <p>凭据只从环境变量注入，源码与配置文件中不得出现真实 api key。
 */
@ConfigurationProperties(prefix = "voice.embedding")
public class EmbeddingProperties {

    /** 本地嵌入服务基址，提供 OpenAI 兼容的 {@code /embeddings} 端点。 */
    private String localEmbeddingBaseUrl = "http://127.0.0.1:8766";

    /** 远端 OpenAI 兼容模式的模型服务基址；留空表示不启用。 */
    private String remoteBaseUrl = "";

    /** 远端模型服务凭据，默认留空并由环境变量 VOICE_EMBEDDING_API_KEY 注入。 */
    private String apiKey = "";

    /** 远端嵌入模型名称；仅在启用远端路径时生效。 */
    private String model = "qwen3.7-text-embedding";

    /** 嵌入向量维度，必须与模型实际输出维度一致，否则 Chroma 集合维度校验会失败。 */
    private int dimensions = 512;

    /** 单次嵌入请求的最大条数。 */
    private int batchSize = 32;

    /**
     * 返回本地嵌入服务基址。
     *
     * @return 服务基址
     */
    public String getLocalEmbeddingBaseUrl() {
        return localEmbeddingBaseUrl;
    }

    /**
     * 设置本地嵌入服务基址。
     *
     * @param localEmbeddingBaseUrl 服务基址
     */
    public void setLocalEmbeddingBaseUrl(String localEmbeddingBaseUrl) {
        this.localEmbeddingBaseUrl = localEmbeddingBaseUrl;
    }

    /**
     * 返回远端模型服务基址。
     *
     * @return 服务基址；空字符串表示未启用
     */
    public String getRemoteBaseUrl() {
        return remoteBaseUrl;
    }

    /**
     * 设置远端模型服务基址。
     *
     * @param remoteBaseUrl 服务基址
     */
    public void setRemoteBaseUrl(String remoteBaseUrl) {
        this.remoteBaseUrl = remoteBaseUrl;
    }

    /**
     * 返回远端模型服务凭据。
     *
     * @return 凭据；空字符串表示未配置
     */
    public String getApiKey() {
        return apiKey;
    }

    /**
     * 设置远端模型服务凭据。
     *
     * @param apiKey 凭据
     */
    public void setApiKey(String apiKey) {
        this.apiKey = apiKey;
    }

    /**
     * 返回远端嵌入模型名称。
     *
     * @return 模型名称
     */
    public String getModel() {
        return model;
    }

    /**
     * 设置远端嵌入模型名称。
     *
     * @param model 模型名称
     */
    public void setModel(String model) {
        this.model = model;
    }

    /**
     * 返回嵌入向量维度。
     *
     * @return 向量维度
     */
    public int getDimensions() {
        return dimensions;
    }

    /**
     * 设置嵌入向量维度。
     *
     * @param dimensions 向量维度
     */
    public void setDimensions(int dimensions) {
        this.dimensions = dimensions;
    }

    /**
     * 返回单次嵌入请求的最大条数。
     *
     * @return 批量上限
     */
    public int getBatchSize() {
        return batchSize;
    }

    /**
     * 设置单次嵌入请求的最大条数。
     *
     * @param batchSize 批量上限
     */
    public void setBatchSize(int batchSize) {
        this.batchSize = batchSize;
    }
}
