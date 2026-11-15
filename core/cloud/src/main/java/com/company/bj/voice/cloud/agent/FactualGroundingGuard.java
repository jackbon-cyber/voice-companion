package com.company.bj.voice.cloud.agent;

import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * 事实约束处理器。
 *
 * <p><b>事实性陈述只允许来自记忆或检索结果</b>（任务 7.8）。
 * 没有来源的具体信息（人名、地点、日期、数字）一律不许出现在回复里 ——
 * 编造一个不存在的地址比说"我记不太清了"伤害大得多。
 *
 * <p><b>检测方式</b>：扫描回复里的<b>具体事实性表述</b>，
 * 再逐个核对它是否出现在上下文或召回的记忆中。
 * 核对用的是<b>归一化后的包含判定</b>，容忍标点与空白差异。
 */
public class FactualGroundingGuard {

    /** 人名模式的匹配正则。
     *
     * <p>允许中间夹一个关系名词（"你妈妈叫李芳"）：
     * 只写 {@code (?:我|你|他|她)\s*(?:叫|名字是)} 会漏掉绝大多数真实说法，
     * 漏检比误报危险 —— 漏检等于形同虚设。
     *
     * <p><b>名字长度用懒惰匹配 {@code {2,4}?} + 边界前瞻</b>：
     * 贪婪匹配会把"李芳对吧"整个吞成名字（4 字），
     * 导致既误报又判错。用边界（标点、语气助词、句尾）确定名字的终点，
     * 才既支持"李芳"（2 字）也支持"李芳芳"（3 字）。 */
    private static final Pattern PERSON_NAME_PATTERN = Pattern.compile(
        "(?:我|你|他|她)(?:的)?(?:[\\u4e00-\\u9fa5]{1,4})?\\s*(?:叫|名字是)\\s*"
            + "([\\u4e00-\\u9fa5]{2,4}?)"
            + "(?=[，。！？、,.!?\\s]|对吧|是不是|吗|呢|啊|呀|了|哦|的|吧|$)");

    /** 地址模式的匹配正则。 */
    private static final Pattern ADDRESS_PATTERN =
        Pattern.compile("(?:住在|住在位于|地址是?)\\s*([^，。！？\\s]{3,20})");

    /** 日期模式的匹配正则。
     *
     * <p><b>只匹配<b>具体</b>日期</b>（"3月15日"），不匹配"今天/昨天/明天"：
     * 相对日期不是可被编造的事实 —— 说"今天"不需要来源，
     * 而把它纳入检查会让大量正常回复被误判。 */
    private static final Pattern DATE_PATTERN =
        Pattern.compile("(\\d{4}\\s*年\\s*\\d{1,2}\\s*月\\d{0,2}\\s*日?|\\d{1,2}\\s*月\\s*\\d{1,2}\\s*日)");

    /** 允许出现而不需来源的通用称呼。 */
    private static final List<String> GENERIC_NAMES = List.of("小柔", "小安");

    /**
     * 校验回复的事实依据。
     *
     * @param reply    待校验的回复
     * @param sources  来源（上下文与召回的记忆）
     * @return 校验结果
     */
    public GroundingResult verify(String reply, List<String> sources) {
        if (reply == null || reply.isBlank()) {
            return new GroundingResult(true, List.of(), "回复为空，无需校验");
        }

        String normalizedSources = normalize(String.join("\n", sources == null ? List.of() : sources));
        List<String> ungrounded = new java.util.ArrayList<>();

        collectUngrounded(PERSON_NAME_PATTERN, reply, normalizedSources, ungrounded);
        collectUngrounded(ADDRESS_PATTERN, reply, normalizedSources, ungrounded);
        collectUngrounded(DATE_PATTERN, reply, normalizedSources, ungrounded);

        if (ungrounded.isEmpty()) {
            return new GroundingResult(true, List.of(), "所有事实性表述均有来源");
        }
        return new GroundingResult(false, ungrounded, "存在无来源的事实性表述");
    }

    /**
     * 收集某一类模式中无来源的匹配。
     *
     * @param pattern         匹配模式
     * @param reply           回复文本
     * @param normalizedSources 归一化后的来源文本
     * @param ungrounded      无来源表述的收集器
     */
    private void collectUngrounded(
        Pattern pattern, String reply, String normalizedSources, List<String> ungrounded) {

        Matcher matcher = pattern.matcher(reply);
        while (matcher.find()) {
            String matched = matcher.group(1);
            if (GENERIC_NAMES.contains(matched)) {
                continue;
            }
            if (!normalizedSources.contains(normalize(matched))) {
                ungrounded.add(matched);
            }
        }
    }

    /**
     * 归一化文本，用于宽松的包含判定。
     *
     * @param text 原始文本
     * @return 归一化结果
     */
    private String normalize(String text) {
        return text.replaceAll("[\\s，。！？、,.!?：:；;\"'“”‘’（）()【】\\[\\]]", "");
    }

    /**
     * 事实校验结果。
     *
     * @param grounded    是否全部有来源
     * @param ungrounded  无来源的事实性表述
     * @param reason      判定说明
     */
    public record GroundingResult(boolean grounded, List<String> ungrounded, String reason) {
    }
}
