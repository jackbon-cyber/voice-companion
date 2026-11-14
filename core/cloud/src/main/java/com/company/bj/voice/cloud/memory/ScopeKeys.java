package com.company.bj.voice.cloud.memory;

/**
 * 作用域存储键与持久化文件名的<b>唯一</b>拥有者。
 *
 * <p><b>为什么必须只有一份</b>：{@code scopeKey} 决定「某个作用域映射到哪个桶」。
 * 工作记忆与情景记忆都用它分桶、各自用它命名持久化文件 ——
 * 若两份实现各自演化，就会出现两种静默故障：
 * <ul>
 *   <li><b>分叉</b>：同一作用域的任务与事件落到不同的键上，跨层检索与诊断都失去基准；</li>
 *   <li><b>碰撞</b>：两个<b>不同</b>的作用域算出同一个键，互相读到对方的数据 ——
 *       这正是跨作用域泄漏，只在数据被读出来时才暴露。</li>
 * </ul>
 * 两类故障都不会抛异常，只会安静地给出错误的数据，因此这个格式必须由单一实现拥有，
 * 由测试持续钉住。
 *
 * <p><b>格式说明</b>：键的格式是「租户长度-租户-主体长度-主体」。
 * 带上长度是为了让 {@code ("a.b", "c")} 与 {@code ("a", "b.c")} 落到<b>不同</b>的键上 ——
 * 若只用一个分隔符直接拼接，这两者会撞进同一个桶，造成跨作用域泄漏。
 * <b>此格式不得简化为单分隔符拼接。</b>
 */
final class ScopeKeys {

    /** 持久化文件扩展名。 */
    static final String FILE_SUFFIX = ".json";

    /** 工具类不允许实例化。 */
    private ScopeKeys() {
        throw new UnsupportedOperationException("utility class");
    }

    /**
     * 构造作用域的存储键。
     *
     * @param scope 作用域
     * @return 存储键
     */
    static String scopeKey(MemoryScope scope) {
        String tenant = scope.tenantId();
        String owner = scope.ownerKey();
        return tenant.length() + "-" + tenant + "-" + owner.length() + "-" + owner;
    }

    /**
     * 按作用域构造持久化文件名。
     *
     * @param configuredName 配置的文件名，为 {@code null} 或空白时使用 {@code defaultName}
     * @param defaultName    未配置时使用的默认文件名
     * @param scope          作用域
     * @return 文件名
     */
    static String scopeFileName(String configuredName, String defaultName, MemoryScope scope) {
        String base = configuredName == null || configuredName.isBlank() ? defaultName : configuredName;
        int suffix = base.endsWith(FILE_SUFFIX) ? base.length() - FILE_SUFFIX.length() : base.length();
        return base.substring(0, suffix) + "-" + scopeKey(scope) + FILE_SUFFIX;
    }
}
