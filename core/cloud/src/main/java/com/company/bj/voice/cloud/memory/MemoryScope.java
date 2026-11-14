package com.company.bj.voice.cloud.memory;

/**
 * 记忆作用域。
 *
 * <p>作用域由「租户」与「主体」两级构成，是四层记忆的<b>隔离边界</b>：
 * 同一段记忆内容在不同作用域下互不可见。
 *
 * <p>作用域<b>不由调用方作为方法入参传入</b>，而是由
 * {@link ScopeResolver} 从当前执行上下文解析（HTTP 请求头
 * {@code X-Tenant-Id} / {@code X-Owner-Key}，缺省为 {@code default}/{@code default}），
 * 以免某个调用点「忘记」传作用域而造成越权读写。
 *
 * @param tenantId  租户标识
 * @param ownerKey  主体标识
 */
public record MemoryScope(String tenantId, String ownerKey) {

    /** 缺省租户标识。 */
    public static final String DEFAULT_TENANT_ID = "default";

    /** 缺省主体标识。 */
    public static final String DEFAULT_OWNER_KEY = "default";

    /**
     * 构造作用域，空白字段回落到缺省值。
     *
     * <p>回落到缺省值而不是抛异常，是因为租户/主体来自 HTTP 请求头，
     * 缺头是<b>正常</b>的调用形态（单机部署、调试），不是错误。
     *
     * @param tenantId 租户标识，为 {@code null} 或空白时取 {@value #DEFAULT_TENANT_ID}
     * @param ownerKey 主体标识，为 {@code null} 或空白时取 {@value #DEFAULT_OWNER_KEY}
     * @return 作用域
     */
    public static MemoryScope of(String tenantId, String ownerKey) {
        return new MemoryScope(
            tenantId == null || tenantId.isBlank() ? DEFAULT_TENANT_ID : tenantId,
            ownerKey == null || ownerKey.isBlank() ? DEFAULT_OWNER_KEY : ownerKey);
    }

    /**
     * 构造缺省作用域（{@code default}/{@code default}）。
     *
     * @return 缺省作用域
     */
    public static MemoryScope defaultScope() {
        return of(DEFAULT_TENANT_ID, DEFAULT_OWNER_KEY);
    }
}
