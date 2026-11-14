package com.company.bj.voice.cloud.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * ChromaDB 服务与集合相关配置。
 *
 * <p>默认值与 {@code application.yml} 中的同名配置保持一致。
 *
 * <p><b>嵌入服务的选择</b>：本工程默认走<b>本地嵌入服务</b>
 * （{@link #localEmbeddingBaseUrl}），而非远端 OpenAI 兼容接口 ——
 * 远端接口需要 API 凭据，而"克隆下来就能跑"是本作品的第一目标。
 * 远端接口保留为可选路径：有凭据时可切换到语义更强的模型。
 */
@ConfigurationProperties(prefix = "voice.chroma")
public class ChromaProperties {

    /** Chroma v2 REST 服务基址，不含任何 /api/v2 路径片段。 */
    private String baseUrl = "http://localhost:8765";

    /** Chroma 租户名，固定为 default_tenant。 */
    private String tenant = "default_tenant";

    /** Chroma 数据库名，固定为 default_database。 */
    private String database = "default_database";

    /** Chroma 持久化数据目录，供启动脚本与健康检查定位。 */
    private String dataPath = "data/chroma";

    /** 知识库集合名，需满足 Chroma 命名规则（3-512 字符，[a-zA-Z0-9._-]，首尾字母数字）。 */
    private String knowledgeCollection = "kb_main";

    /** 长期记忆集合名，需满足 Chroma 命名规则。 */
    private String memoryCollection = "mem_longterm";

    /**
     * 返回 Chroma 服务基址。
     *
     * @return 服务基址
     */
    public String getBaseUrl() {
        return baseUrl;
    }

    /**
     * 设置 Chroma 服务基址。
     *
     * @param baseUrl 服务基址
     */
    public void setBaseUrl(String baseUrl) {
        this.baseUrl = baseUrl;
    }

    /**
     * 返回 Chroma 租户名。
     *
     * @return 租户名
     */
    public String getTenant() {
        return tenant;
    }

    /**
     * 设置 Chroma 租户名。
     *
     * @param tenant 租户名
     */
    public void setTenant(String tenant) {
        this.tenant = tenant;
    }

    /**
     * 返回 Chroma 数据库名。
     *
     * @return 数据库名
     */
    public String getDatabase() {
        return database;
    }

    /**
     * 设置 Chroma 数据库名。
     *
     * @param database 数据库名
     */
    public void setDatabase(String database) {
        this.database = database;
    }

    /**
     * 返回 Chroma 持久化数据目录。
     *
     * @return 数据目录
     */
    public String getDataPath() {
        return dataPath;
    }

    /**
     * 设置 Chroma 持久化数据目录。
     *
     * @param dataPath 数据目录
     */
    public void setDataPath(String dataPath) {
        this.dataPath = dataPath;
    }

    /**
     * 返回知识库集合名。
     *
     * @return 集合名
     */
    public String getKnowledgeCollection() {
        return knowledgeCollection;
    }

    /**
     * 设置知识库集合名。
     *
     * @param knowledgeCollection 集合名
     */
    public void setKnowledgeCollection(String knowledgeCollection) {
        this.knowledgeCollection = knowledgeCollection;
    }

    /**
     * 返回长期记忆集合名。
     *
     * @return 集合名
     */
    public String getMemoryCollection() {
        return memoryCollection;
    }

    /**
     * 设置长期记忆集合名。
     *
     * @param memoryCollection 集合名
     */
    public void setMemoryCollection(String memoryCollection) {
        this.memoryCollection = memoryCollection;
    }
}
