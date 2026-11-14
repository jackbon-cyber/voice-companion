package com.company.bj.voice.cloud.chroma;

/**
 * Chroma 服务健康指示器。
 *
 * <p>通过读取服务端版本号判断 Chroma 是否可用：版本端点是最轻量的探活路径，
 * 不触碰任何集合数据。{@link #isHealthy()} 面向"给我一个布尔结论"的场景
 * （如就绪探针），{@link #version()} 面向需要把失败原因暴露给调用方的场景。
 */
public class ChromaHealthIndicator {

    private final ChromaClient client;

    /**
     * 构造健康指示器。
     *
     * @param client 用于探活的 Chroma 客户端
     */
    public ChromaHealthIndicator(ChromaClient client) {
        this.client = client;
    }

    /**
     * 判断 Chroma 服务是否健康。
     *
     * <p>任何异常（连接失败、非 2xx 响应、响应体无法解析）都判定为不健康，
     * 因为健康检查的语义是"能否用"，而非"为什么不能用"。
     *
     * @return 服务可用返回 {@code true}，否则返回 {@code false}
     */
    public boolean isHealthy() {
        try {
            client.version();
            return true;
        } catch (RuntimeException e) {
            return false;
        }
    }

    /**
     * 读取 Chroma 服务端版本号。
     *
     * @return 服务端版本号
     * @throws ChromaException 服务端返回非 2xx、连接失败或响应体无法解析
     */
    public String version() {
        return client.version();
    }
}
