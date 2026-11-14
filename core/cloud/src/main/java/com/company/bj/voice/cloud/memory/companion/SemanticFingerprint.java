package com.company.bj.voice.cloud.memory.companion;

import java.text.Normalizer;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 归一化语义指纹。
 *
 * <p>作为记忆写入的<b>幂等键</b>：语义等价的不同表述命中同一把指纹，
 * 因此只产生一条记录。
 *
 * <p><b>归一化做四件事</b>：
 * <ol>
 *   <li>Unicode NFKC 归一 —— 全角"Ａ"与半角"A"视为同一个字；</li>
 *   <li>去除标点与空白 —— "我妈妈叫李芳。"与"我妈妈叫李芳"同指；</li>
 *   <li>中文数字转阿拉伯数字 —— "二十八"与"28"同指；</li>
 *   <li>大小写归一 —— 英文内容不区分大小写。</li>
 * </ol>
 *
 * <p><b>它不是语义模型</b>：它只消除<b>表述层面的差异</b>，
 * 不消除<b>语义层面的差异</b>。"我妈妈叫李芳"与"我母亲叫李芳"归一化后
 * 仍不同 —— 那需要嵌入模型来判定，属于指纹之外的语义去重环节。
 * 指纹保证的是"同一句话说两次不会写两遍"，
 * 这正是幂等性所需的最小保证。
 */
public final class SemanticFingerprint {

    /** 标点与空白字符，统一剔除。 */
    private static final Pattern PUNCTUATION_OR_SPACE = Pattern.compile("[\\p{P}\\p{Z}\\s]+");

    /** 连续的中文数字字符。 */
    private static final Pattern CHINESE_NUMERAL_RUN = Pattern.compile("[零〇一二两三四五六七八九十百]+");

    /** 中文数字与阿拉伯数字的单字对应表。 */
    private static final String[][] SINGLE_DIGITS = {
        {"零", "0"}, {"〇", "0"}, {"一", "1"}, {"二", "2"}, {"两", "2"},
        {"三", "3"}, {"四", "4"}, {"五", "5"}, {"六", "6"},
        {"七", "7"}, {"八", "8"}, {"九", "9"}
    };

    /** 工具类不允许实例化。 */
    private SemanticFingerprint() {
        throw new UnsupportedOperationException("utility class");
    }

    /**
     * 计算一段内容的归一化指纹。
     *
     * @param content 待计算的内容
     * @return 归一化后的指纹文本；内容为空白时返回空字符串
     */
    public static String of(String content) {
        if (content == null || content.isBlank()) {
            return "";
        }
        String normalized = Normalizer.normalize(content, Normalizer.Form.NFKC);
        normalized = normalized.toLowerCase(Locale.ROOT);
        normalized = PUNCTUATION_OR_SPACE.matcher(normalized).replaceAll("");
        normalized = convertChineseNumerals(normalized);
        return normalized;
    }

    /**
     * 判断两段内容是否语义等价（同指纹）。
     *
     * @param left  左侧内容
     * @param right 右侧内容
     * @return 指纹相同返回 {@code true}
     */
    public static boolean equivalent(String left, String right) {
        String leftFingerprint = of(left);
        return !leftFingerprint.isEmpty() && leftFingerprint.equals(of(right));
    }

    /**
     * 把文本中的中文数字串转成阿拉伯数字。
     *
     * @param text 已转小写并去标点的文本
     * @return 转换后的文本
     */
    private static String convertChineseNumerals(String text) {
        Matcher matcher = CHINESE_NUMERAL_RUN.matcher(text);
        StringBuilder result = new StringBuilder(text.length());
        int lastEnd = 0;
        while (matcher.find()) {
            result.append(text, lastEnd, matcher.start());
            result.append(parseChineseNumeral(matcher.group()));
            lastEnd = matcher.end();
        }
        result.append(text, lastEnd, text.length());
        return result.toString();
    }

    /**
     * 解析一段中文数字。
     *
     * <p>支持到百位，覆盖"十 / 二十八 / 一百零五"等常见写法。
     * 无法解析时原样返回，避免把无法理解的数字改写成错误的数字 ——
     * 错误的归一化比不归一化更危险。
     *
     * @param run 中文数字串
     * @return 阿拉伯数字文本
     */
    private static String parseChineseNumeral(String run) {
        if (run.isEmpty()) {
            return run;
        }
        int hundredIndex = run.indexOf('百');
        if (hundredIndex < 0) {
            return parseBelowHundred(run);
        }
        int hundreds = digitOf(run.charAt(0));
        if (hundreds < 0) {
            return run;
        }
        String remainder = run.substring(hundredIndex + 1);
        if (remainder.isEmpty()) {
            return String.valueOf(hundreds * 100);
        }
        String lower = parseBelowHundred(remainder);
        if (lower.equals(remainder)) {
            return run;
        }
        return String.valueOf(hundreds * 100 + Integer.parseInt(lower));
    }

    /**
     * 解析百位以下的中文数字。
     *
     * @param run 中文数字串
     * @return 阿拉伯数字文本；无法解析时原样返回
     */
    private static String parseBelowHundred(String run) {
        int tenIndex = run.indexOf('十');
        if (tenIndex < 0) {
            int digit = digitOf(run.charAt(0));
            if (run.length() != 1 || digit < 0) {
                return run;
            }
            return String.valueOf(digit);
        }
        int tens = tenIndex == 0 ? 1 : digitOf(run.charAt(0));
        if (tens < 0) {
            return run;
        }
        String onesPart = run.substring(tenIndex + 1);
        int ones = 0;
        if (!onesPart.isEmpty()) {
            if (onesPart.length() > 1) {
                return run;
            }
            ones = digitOf(onesPart.charAt(0));
            if (ones < 0) {
                return run;
            }
        }
        return String.valueOf(tens * 10 + ones);
    }

    /**
     * 取单个中文字符的数字值。
     *
     * @param character 中文字符
     * @return 数字值；不是数字返回 {@code -1}
     */
    private static int digitOf(char character) {
        for (String[] pair : SINGLE_DIGITS) {
            if (pair[0].charAt(0) == character) {
                return Integer.parseInt(pair[1]);
            }
        }
        return -1;
    }
}
