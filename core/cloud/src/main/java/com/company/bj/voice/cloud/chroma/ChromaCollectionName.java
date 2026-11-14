package com.company.bj.voice.cloud.chroma;

import java.util.regex.Pattern;

/**
 * Chroma 集合名校验。
 *
 * <p>Chroma v2 服务端要求集合名长度 3–512，字符集限定为 {@code [a-zA-Z0-9._-]}，
 * 且首尾字符必须为字母数字。服务端对违规名称返回 4xx，本地先做校验可以在
 * **发起任何 HTTP 请求之前**把非法名称拦下，避免无谓网络往返，
 * 同时让调用方拿到语义明确的 {@link IllegalArgumentException}。
 */
public final class ChromaCollectionName {

    /** 集合名最小长度。 */
    public static final int MIN_LENGTH = 3;

    /** 集合名最大长度。 */
    public static final int MAX_LENGTH = 512;

    /** 集合名合法字符集。 */
    private static final Pattern NAME_PATTERN = Pattern.compile("^[a-zA-Z0-9._-]{3,512}$");

    /** 集合名首字符必须为字母数字。 */
    private static final Pattern ALPHANUMERIC_PREFIX = Pattern.compile("^[a-zA-Z0-9]");

    /** 集合名尾字符必须为字母数字。 */
    private static final Pattern ALPHANUMERIC_SUFFIX = Pattern.compile("[a-zA-Z0-9]$");

    private ChromaCollectionName() {
        throw new IllegalStateException("工具类不允许实例化");
    }

    /**
     * 校验集合名是否合法，合法则原样返回。
     *
     * @param name 待校验的集合名
     * @return 校验通过的集合名（原样返回）
     * @throws IllegalArgumentException 名称为空、超长、含非法字符或首尾非字母数字时抛出，
     *                                  消息中包含 {@code collection name} 以便调用方定位
     */
    public static String validate(String name) {
        if (name == null || !NAME_PATTERN.matcher(name).matches()) {
            throw new IllegalArgumentException(
                "invalid collection name: '" + name + "', expected length " + MIN_LENGTH + "-" + MAX_LENGTH
                    + " with charset [a-zA-Z0-9._-] and alphanumeric first/last character");
        }
        if (!ALPHANUMERIC_PREFIX.matcher(name).find() || !ALPHANUMERIC_SUFFIX.matcher(name).find()) {
            throw new IllegalArgumentException(
                "invalid collection name: '" + name + "', first and last character must be alphanumeric");
        }
        return name;
    }
}
