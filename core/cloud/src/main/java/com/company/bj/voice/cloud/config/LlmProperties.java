package com.company.bj.voice.cloud.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 云端大模型（对话生成）相关配置。
 *
 * <p><b>本工程默认不依赖大模型</b>：云端回复走模板式记忆引用
 * （{@code MemoryGroundedReplyService}），完全离线可跑 ——
 * 这是"克隆下来 10 分钟内看到效果"的前提。
 *
 * <p>配置了 {@link #baseUrl} 与 {@link #apiKey} 之后，
 * 记忆命中的内容会被交给大模型改写成更自然的陪伴式表达。
 * **引用来源（citations）仍由代码填充**，不由模型生成 ——
 * 详见 {@code LlmReplyGenerator} 的类注释。
 *
 * <p>凭据只从环境变量注入，源码与配置文件中不得出现真实 api key。
 */
@ConfigurationProperties(prefix = "voice.llm")
public class LlmProperties {

    /** 大模型服务基址（OpenAI 兼容模式）；留空表示不启用，回复退回模板。 */
    private String baseUrl = "";

    /** 大模型服务凭据，默认留空并由环境变量 {@code VOICE_LLM_API_KEY} 注入。 */
    private String apiKey = "";

    /** 模型名称。 */
    private String model = "qwen-plus";

    /** 单次请求超时秒数。陪伴场景对延迟敏感，超时必须短 —— 超时后立刻退回模板。 */
    private int timeoutSeconds = 15;

    /** 生成回复的最大 token 数。陪伴回复通常很短，给多了只是拖慢响应。 */
    private int maxTokens = 200;

    /**
     * 判断是否启用大模型路径。
     *
     * <p>基址与凭据<b>都</b>非空才启用：只配其一多半是配置写错了，
     * 与其发起注定失败的请求，不如直接走模板路径并让日志指明缺哪一项。
     *
     * @return 启用返回 {@code true}
     */
    public boolean enabled() {
        return baseUrl != null && !baseUrl.isBlank()
            && apiKey != null && !apiKey.isBlank();
    }

    /**
     * 返回服务基址。
     *
     * @return 服务基址；空字符串表示未启用
     */
    public String getBaseUrl() {
        return baseUrl;
    }

    /**
     * 设置服务基址。
     *
     * @param baseUrl 服务基址
     */
    public void setBaseUrl(String baseUrl) {
        this.baseUrl = baseUrl;
    }

    /**
     * 返回服务凭据。
     *
     * @return 凭据；空字符串表示未配置
     */
    public String getApiKey() {
        return apiKey;
    }

    /**
     * 设置服务凭据。
     *
     * @param apiKey 凭据
     */
    public void setApiKey(String apiKey) {
        this.apiKey = apiKey;
    }

    /**
     * 返回模型名称。
     *
     * @return 模型名称
     */
    public String getModel() {
        return model;
    }

    /**
     * 设置模型名称。
     *
     * @param model 模型名称
     */
    public void setModel(String model) {
        this.model = model;
    }

    /**
     * 返回请求超时秒数。
     *
     * @return 超时秒数
     */
    public int getTimeoutSeconds() {
        return timeoutSeconds;
    }

    /**
     * 设置请求超时秒数。
     *
     * @param timeoutSeconds 超时秒数
     */
    public void setTimeoutSeconds(int timeoutSeconds) {
        this.timeoutSeconds = timeoutSeconds;
    }

    /**
     * 返回单次生成的最大 token 数。
     *
     * @return 最大 token 数
     */
    public int getMaxTokens() {
        return maxTokens;
    }

    /**
     * 设置单次生成的最大 token 数。
     *
     * @param maxTokens 最大 token 数
     */
    public void setMaxTokens(int maxTokens) {
        this.maxTokens = maxTokens;
    }
}
