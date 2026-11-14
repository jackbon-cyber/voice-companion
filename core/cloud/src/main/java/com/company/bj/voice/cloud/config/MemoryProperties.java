package com.company.bj.voice.cloud.config;

import org.springframework.boot.context.properties.ConfigurationProperties;

/**
 * 记忆层运行时配置。
 *
 * <p>承载查询向量缓存 TTL 与工作记忆、情景记忆的<b>持久化路径</b>。
 * 这两层记忆需要跨进程重启保留内容，因此落盘为 JSON 文件，
 * 路径由 {@code dataPath} 与两个文件名共同决定。
 *
 * <p>配置前缀为 {@code voice.memory}，与上游 {@code memorykb.memory} 区分 ——
 * 两套工程并存时，前缀不同才能各自读取自己的配置。
 */
@ConfigurationProperties(prefix = "voice.memory")
public class MemoryProperties {

    /** 查询向量缓存存活秒数，过期后重新向嵌入服务请求。 */
    private long queryCacheTtlSeconds = 60;

    /** 记忆持久化数据目录，工作记忆与情景记忆的 JSON 文件都落在这里。 */
    private String dataPath = "data/memory";

    /** 工作记忆持久化文件名，位于 {@link #dataPath} 之下。 */
    private String workingMemoryFile = "working-memory.json";

    /** 情景记忆持久化文件名，位于 {@link #dataPath} 之下。 */
    private String episodicMemoryFile = "episodic-memory.json";

    /**
     * 返回查询向量缓存存活秒数。
     *
     * @return 缓存存活秒数
     */
    public long getQueryCacheTtlSeconds() {
        return queryCacheTtlSeconds;
    }

    /**
     * 设置查询向量缓存存活秒数。
     *
     * @param queryCacheTtlSeconds 缓存存活秒数
     */
    public void setQueryCacheTtlSeconds(long queryCacheTtlSeconds) {
        this.queryCacheTtlSeconds = queryCacheTtlSeconds;
    }

    /**
     * 返回记忆持久化数据目录。
     *
     * @return 数据目录
     */
    public String getDataPath() {
        return dataPath;
    }

    /**
     * 设置记忆持久化数据目录。
     *
     * @param dataPath 数据目录
     */
    public void setDataPath(String dataPath) {
        this.dataPath = dataPath;
    }

    /**
     * 返回工作记忆持久化文件名。
     *
     * @return 文件名
     */
    public String getWorkingMemoryFile() {
        return workingMemoryFile;
    }

    /**
     * 设置工作记忆持久化文件名。
     *
     * @param workingMemoryFile 文件名
     */
    public void setWorkingMemoryFile(String workingMemoryFile) {
        this.workingMemoryFile = workingMemoryFile;
    }

    /**
     * 返回情景记忆持久化文件名。
     *
     * @return 文件名
     */
    public String getEpisodicMemoryFile() {
        return episodicMemoryFile;
    }

    /**
     * 设置情景记忆持久化文件名。
     *
     * @param episodicMemoryFile 文件名
     */
    public void setEpisodicMemoryFile(String episodicMemoryFile) {
        this.episodicMemoryFile = episodicMemoryFile;
    }
}
