package com.company.bj.voice.cloud.chroma;

/**
 * Chroma v2 REST 路径构造。
 *
 * <p>Chroma v2 的接口基址形如
 * {@code /api/v2/tenants/{tenant}/databases/{database}/collections/{collection_id}}，
 * v1 的 {@code /api/v1/*} 已被服务端移除（返回 410），因此所有路径都只能在此集中构造，
 * 避免各调用点自行拼接导致版本漂移。
 *
 * <p>本类只产出**相对路径**（不含 baseUrl），由 {@link ChromaClient} 负责与基址拼接。
 */
public final class ChromaPaths {

    /** Chroma v2 版本查询路径。 */
    private static final String VERSION_PATH = "/api/v2/version";

    /** Chroma v2 集合资源的路径前缀模板。 */
    private static final String COLLECTIONS_TEMPLATE = "/api/v2/tenants/%s/databases/%s/collections";

    private ChromaPaths() {
        throw new IllegalStateException("工具类不允许实例化");
    }

    /**
     * 返回服务端版本查询路径。
     *
     * @return 相对路径 {@code /api/v2/version}
     */
    public static String version() {
        return VERSION_PATH;
    }

    /**
     * 返回某个租户/数据库下的集合列表路径。
     *
     * @param tenant  租户名
     * @param database 数据库名
     * @return 相对路径
     */
    public static String collections(String tenant, String database) {
        return String.format(COLLECTIONS_TEMPLATE, tenant, database);
    }

    /**
     * 返回某个具体集合的路径。
     *
     * @param tenant       租户名
     * @param database     数据库名
     * @param collectionId 集合 id
     * @return 相对路径
     */
    public static String collection(String tenant, String database, String collectionId) {
        return collections(tenant, database) + "/" + collectionId;
    }
}
