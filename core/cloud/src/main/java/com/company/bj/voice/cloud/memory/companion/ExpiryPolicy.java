package com.company.bj.voice.cloud.memory.companion;

import java.time.Duration;

/**
 * 时效记忆的过期策略。
 *
 * <p>时效事件（明天体检、下周出差）归入长期记忆，但会带一个过期时间。
 * 过期后该记忆<b>退出活跃召回集合</b>，但<b>仍可追溯</b> ——
 * 这两件事必须同时成立：退出召回是"不再拿它干扰当前对话"，
 * 可追溯是"用户三个月后问起时仍能查到"。
 *
 * <p><b>两个方法的语义刻意不同</b>：
 * <ul>
 *   <li>{@link #estimateExpiry} 只在内容<b>含明确时长线索</b>时给出过期时间，
 *       否则返回 {@code 0}（永不过期）；</li>
 *   <li>{@link #defaultExpiry} 用于「已被分类为时效事件但没说什么时候」的情形，
 *       给一个保守的默认有效期。</li>
 * </ul>
 * 分开的原因：把两者混为一谈会让"我妈妈叫李芳"这类根本不含时间的信息
 * 也被赋予过期时间 —— 那会让长期记忆莫名其妙地消失。
 */
public class ExpiryPolicy {

    /** 默认时效天数：未指明时长的事件默认一周内有效。 */
    public static final int DEFAULT_VALIDITY_DAYS = 7;

    /** 时长线索与天数的对应表。<b>顺序敏感</b>：更具体的线索必须排在更宽泛的前面，
     * 否则"大后天"会先命中"后天"而被算成两天，"今天晚上"会先命中"今天"。
     * 判据是<b>包含关系</b>，不是长度直觉。 */
    private static final String[][] DURATION_MARKERS = {
        {"今天晚上", "1"}, {"今晚", "1"}, {"今天", "1"},
        {"一会儿", "1"}, {"等一下", "1"}, {"等会", "1"},
        {"大后天", "3"}, {"后天", "2"}, {"明天", "1"},
        {"下周", "7"}, {"下个月", "30"},
        {"两天", "2"}, {"三天", "3"}, {"四天", "4"}, {"五天", "5"},
        {"六天", "6"}, {"七天", "7"}, {"过几天", "3"},
        {"一周", "7"}, {"两周", "14"}, {"三周", "21"},
        {"一个月", "30"}, {"两个月", "60"}, {"三个月", "90"},
        {"周末", "7"}, {"月底", "30"}, {"年底", "90"}
    };

    /**
     * 判断一条记忆在给定时刻是否已过期。
     *
     * @param expiresAt 过期时间戳；{@code 0} 表示永不过期
     * @param now       当前时间戳
     * @return 已过期返回 {@code true}
     */
    public boolean isExpired(long expiresAt, long now) {
        if (expiresAt <= 0L) {
            return false;
        }
        return now >= expiresAt;
    }

    /**
     * 估算一段时效内容的过期时间。
     *
     * @param content 内容文本
     * @param now     当前时间戳
     * @return 过期时间戳；内容不含明确时长线索时返回 {@code 0}（永不过期）
     */
    public long estimateExpiry(String content, long now) {
        if (content == null || content.isBlank()) {
            return 0L;
        }
        int days = extractValidityDays(content);
        if (days <= 0) {
            return 0L;
        }
        return now + Duration.ofDays(days).toMillis();
    }

    /**
     * 给出默认有效期。
     *
     * <p>用于「内容已被判定为时效事件，但没有说明具体什么时候」的情形。
     *
     * @param now 当前时间戳
     * @return 默认过期时间戳
     */
    public long defaultExpiry(long now) {
        return now + Duration.ofDays(DEFAULT_VALIDITY_DAYS).toMillis();
    }

    /**
     * 从内容中抽取有效期天数。
     *
     * @param content 内容文本
     * @return 天数；未识别到时长线索时返回 {@code 0}
     */
    public int extractValidityDays(String content) {
        if (content == null || content.isBlank()) {
            return 0;
        }
        for (String[] marker : DURATION_MARKERS) {
            if (content.contains(marker[0])) {
                return Integer.parseInt(marker[1]);
            }
        }
        return 0;
    }
}
