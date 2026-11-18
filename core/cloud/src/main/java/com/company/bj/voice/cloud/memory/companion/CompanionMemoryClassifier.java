package com.company.bj.voice.cloud.memory.companion;

import java.util.List;
import java.util.Locale;

/**
 * 陪伴域记忆分类器。
 *
 * <p>把一轮对话里的若干条候选内容分到 {@link CompanionMemoryCategory} 的六个类。
 *
 * <p><b>为什么用规则而不是模型</b>：分类错误的代价极不对称 ——
 * 把"今天有点累"写进长期记忆会污染后续召回，而把一次性指令漏进长期记忆
 * 只是多一条噪音。规则表能被单元测试逐条钉死，且<b>零延迟、零凭据依赖</b>；
 * 模型分类在陪伴场景里既慢又不可复现（同一句话两次判定可能不同），
 * 而记忆写入是<b>不可撤销的事实性操作</b>，需要确定性。
 *
 * <p><b>判定顺序有意义</b>：具体类别先判，通用类别后判。
 * "把音量调到五十"同时命中"一次性指令"与"寒暄"，但指令语义更具体；
 * "今天好累"同时命中"情绪"与"寒暄"，情绪语义更具体。
 */
public class CompanionMemoryClassifier {

    /** 关系事实关键词。 */
    private static final List<String> RELATIONSHIP_KEYWORDS = List.of(
            "我妈妈", "我妈", "我爸爸", "我爸", "我哥哥", "我弟弟", "我姐姐", "我妹妹",
            "我老婆", "我妻子", "我老公", "我丈夫", "我女儿", "我儿子", "我孩子",
            "我奶奶", "我爷爷", "我外婆", "我外公", "我朋友", "我同事", "我老板",
            "我爱人", "我对象", "我女朋友", "我男朋友", "我表", "我堂", "我舅", "我姨");

    /** 关系事实的补充模式：显式陈述"名字/叫/是"。 */
    private static final List<String> RELATIONSHIP_PATTERNS = List.of(
            "叫", "名字叫", "名字是", "她叫", "他叫");

    /** 稳定偏好关键词。 */
    private static final List<String> PREFERENCE_KEYWORDS = List.of(
            "我喜欢", "我爱吃", "我不喜欢", "我讨厌", "我最爱", "我最喜欢", "我偏好", "我习惯",
            "我一般", "我通常", "我不习惯", "我受不了", "我怕", "我最爱吃", "我最喜欢吃");

    /** 一次性指令关键词。 */
    private static final List<String> INSTRUCTION_KEYWORDS = List.of(
            "音量", "声音大", "声音小", "大声", "小声", "播放", "放一首", "放首", "来一首",
            "来首", "暂停", "继续", "停止", "别说了", "安静", "打开", "关上", "重启",
            "设置成", "调成", "调到", "换成", "下一首", "上一首");

    /** 时效事件关键词。 */
    private static final List<String> TIME_SENSITIVE_KEYWORDS = List.of(
            "明天", "后天", "下周", "下个月", "周末", "今晚", "今天晚上", "一会儿",
            "等会", "等一下", "一会儿后", "过几天", "月底", "年底", "假期", "出差",
            "考试", "面试", "体检", "生日");

    /** 情绪关键词。 */
    private static final List<String> EMOTION_KEYWORDS = List.of(
            "开心", "高兴", "难过", "伤心", "生气", "愤怒", "焦虑", "紧张", "害怕",
            "孤独", "寂寞", "累", "疲惫", "烦", "沮丧", "失落", "兴奋", "感动",
            "委屈", "绝望", "崩溃", "欣慰", "平静", "放松");

    /** 寒暄关键词。 */
    private static final List<String> SMALL_TALK_KEYWORDS = List.of(
        "你好", "您好", "早上好", "晚安", "再见", "拜拜", "谢谢", "不客气",
        "在吗", "吃了吗", "睡了", "起床", "哈哈", "呵呵", "嘿嘿");

    /**
     * 疑问标记。
     *
     * <p><b>为什么需要单独判定</b>：疑问句里也会出现关系词与偏好词 ——
     * "我妈妈叫什么"含"我妈妈"，"我喜欢什么"含"我喜欢"。
     * 若不剔除，它们会被当成用户陈述的事实写进长期记忆，
     * 把**提问本身**当成记忆内容存下来。
     *
     * <p>后果不是"多一条噪音"而是**污染召回**：
     * 用户问"我妈妈叫什么"，召回结果里混进"我妈妈叫什么"这条问句，
     * 机器人会答"你说你想知道你妈妈叫什么" —— 看起来像坏了。
     */
    private static final List<String> QUESTION_MARKERS = List.of(
        "什么", "谁", "为什么", "怎么", "怎样", "如何", "多少", "哪些", "哪个",
        "吗", "呢", "？", "?");

    /**
     * 返回记忆分类器使用的全部关键词。
     *
     * <p>暴露出来是为了让评测集做<b>语料交集检查</b>：
     * 评测集里若混进了这些关键词构成的句子，
     * 测出来的召回率衡量的是背诵而不是泛化。
     *
     * <p>调用方拿到的是<b>不可变副本</b>，改不动内部状态。
     *
     * @return 全部关键词
     */
    public static List<String> keywords() {
        return List.of(
            RELATIONSHIP_KEYWORDS, RELATIONSHIP_PATTERNS, PREFERENCE_KEYWORDS,
            INSTRUCTION_KEYWORDS, TIME_SENSITIVE_KEYWORDS, EMOTION_KEYWORDS,
            SMALL_TALK_KEYWORDS).stream().flatMap(List::stream).toList();
    }

    /**
     * 判定一条内容的分类。
     *
     * @param content 待判定内容
     * @return 分类结果；内容为空白时返回 {@link CompanionMemoryCategory#SMALL_TALK}
     */
    public CompanionMemoryCategory classify(String content) {
        if (content == null || content.isBlank()) {
            return CompanionMemoryCategory.SMALL_TALK;
        }
        String text = content.toLowerCase(Locale.ROOT);

        // 疑问句优先判定：疑问句里同样会出现关系词与偏好词，
        // 不先剔除就会把"提问"当成"陈述的事实"写进长期记忆。
        if (isQuestion(text)) {
            return CompanionMemoryCategory.SMALL_TALK;
        }

        if (containsAny(text, TIME_SENSITIVE_KEYWORDS)) {
            return CompanionMemoryCategory.TIME_SENSITIVE_EVENT;
        }
        if (containsAny(text, RELATIONSHIP_KEYWORDS) || matchesRelationshipPattern(text)) {
            return CompanionMemoryCategory.RELATIONSHIP_FACT;
        }
        if (containsAny(text, PREFERENCE_KEYWORDS)) {
            return CompanionMemoryCategory.STABLE_PREFERENCE;
        }
        if (containsAny(text, INSTRUCTION_KEYWORDS)) {
            return CompanionMemoryCategory.ONE_SHOT_INSTRUCTION;
        }
        if (containsAny(text, EMOTION_KEYWORDS)) {
            return CompanionMemoryCategory.CURRENT_EMOTION;
        }
        return CompanionMemoryCategory.SMALL_TALK;
    }

    /**
     * 判断内容是否为一次性指令。
     *
     * @param content 待判定内容
     * @return 是一次性指令返回 {@code true}
     */
    public boolean isOneShotInstruction(String content) {
        return CompanionMemoryCategory.ONE_SHOT_INSTRUCTION == classify(content);
    }

    /**
     * 判断内容是否应归入长期记忆。
     *
     * @param content 待判定内容
     * @return 应归入长期记忆返回 {@code true}
     */
    public boolean shouldPersistLongTerm(String content) {
        return classify(content).longTerm();
    }

    /**
     * 判断文本是否包含给定关键词之一。
     *
     * @param text      已转小写的文本
     * @param keywords 关键词列表
     * @return 命中返回 {@code true}
     */
    private boolean containsAny(String text, List<String> keywords) {
        return keywords.stream().anyMatch(text::contains);
    }

    /**
     * 判断文本是否呈现"关系 + 显式陈述"的组合。
     *
     * <p>单看"叫"会误判："这菜叫水煮鱼"不是关系事实。
     * 因此要求文本中同时出现代词（我/她/他/我们）与陈述动词（叫/名字）。
     *
     * @param text 已转小写的文本
     * @return 命中返回 {@code true}
     */
    private boolean matchesRelationshipPattern(String text) {
        boolean hasSubject = text.contains("我") || text.contains("她") || text.contains("他");
        boolean hasStatement = RELATIONSHIP_PATTERNS.stream().anyMatch(text::contains);
        return hasSubject && hasStatement;
    }

    /**
     * 判断文本是否是疑问句。
     *
     * <p>判定方式是**疑问词 + 句末语气词**的组合，不是单个疑问词 ——
     * "我不知道"含"不"但不是疑问，"什么"本身也可能出现在陈述里
     * （"这些东西我都知道"）。
     *
     * @param text 已转小写的文本
     * @return 是疑问句返回 {@code true}
     */
    private boolean isQuestion(String text) {
        boolean hasQuestionWord = containsAny(text, QUESTION_MARKERS);
        // 句末语气词（吗/呢）是中文疑问句最可靠的信号。
        boolean hasSentenceFinalParticle =
                text.endsWith("吗") || text.endsWith("呢") || text.endsWith("？")
                    || text.endsWith("?");
        return hasQuestionWord && (hasSentenceFinalParticle || text.contains("什么")
                || text.contains("谁") || text.contains("为什么") || text.contains("多少"));
    }
}
