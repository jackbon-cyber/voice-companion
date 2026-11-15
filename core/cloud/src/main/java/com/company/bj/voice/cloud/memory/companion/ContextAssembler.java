package com.company.bj.voice.cloud.memory.companion;

import java.util.ArrayList;
import java.util.List;

/**
 * 会话上下文装配器。
 *
 * <p>把五类上下文按<b>固定顺序</b>装配成一段可直接送入模型的提示词：
 * <ol>
 *   <li>人设卡（Persona）</li>
 *   <li>画像卡（Profile）</li>
 *   <li>长期记忆（LongTermMemory）</li>
 *   <li>短期历史（ShortTermHistory）</li>
 *   <li>当前轮（CurrentTurn）</li>
 * </ol>
 *
 * <p><b>顺序不可调换</b>：越靠前的内容对模型输出的影响越大。
 * 人设必须在最前 —— 否则模型可能学成用户的语气而不是陪伴者的语气。
 * 当前轮必须在最后 —— 它离输出最近，最不容易被前面的长上下文挤掉。
 *
 * <p><b>预算超限时的牺牲顺序</b>（从先牺牲到后牺牲）：
 * <ol>
 *   <li>长期记忆 —— 是"可再召回的资料"，丢了可以下次补；</li>
 *   <li>最早的短期历史 —— 越早的对话越不重要；</li>
 *   <li>人设与画像 —— 是"配置"而非"上下文"，原则上不牺牲，
 *       只有它们本身就超预算时才截断（并明确标记）。</li>
 * </ol>
 */
public class ContextAssembler {

    /** 默认上下文预算（字符数）。 */
    public static final int DEFAULT_BUDGET = 2000;

    /** 各部分的分隔符。 */
    private static final String SECTION_SEPARATOR = "\n\n";

    /** 人设段的标题。 */
    public static final String PERSONA_HEADER = "【人设】";

    /** 画像段的标题。 */
    public static final String PROFILE_HEADER = "【画像】";

    /** 记忆段的标题。 */
    public static final String MEMORY_HEADER = "【记忆】";

    /** 短期历史段的标题。 */
    public static final String HISTORY_HEADER = "【近期对话】";

    /** 当前轮段的标题。 */
    public static final String CURRENT_TURN_HEADER = "【当前轮】";

    /** 默认预算。 */
    private final int budget;

    /**
     * 构造装配器，使用默认预算。
     */
    public ContextAssembler() {
        this(DEFAULT_BUDGET);
    }

    /**
     * 构造装配器。
     *
     * @param budget 上下文预算（字符数）
     */
    public ContextAssembler(int budget) {
        this.budget = budget;
    }

    /**
     * 装配上下文。
     *
     * @param persona     人设卡内容；可为空
     * @param profile     画像卡内容；可为空
     * @param memories    长期记忆列表；可为空
     * @param history     短期历史列表；可为空
     * @param currentTurn 当前轮用户文本
     * @return 装配后的上下文
     */
    public AssembledContext assemble(
        String persona,
        String profile,
        List<String> memories,
        List<String> history,
        String currentTurn) {

        List<Section> sections = buildSections(persona, profile, memories, history, currentTurn);
        String assembled = render(sections);

        if (assembled.length() <= budget) {
            return new AssembledContext(assembled, List.of(), assembled.length(), budget);
        }

        return truncate(sections);
    }

    /**
     * 按固定顺序构造各段落。
     *
     * @param persona     人设卡内容
     * @param profile     画像卡内容
     * @param memories    长期记忆
     * @param history     短期历史
     * @param currentTurn 当前轮
     * @return 段落列表
     */
    private List<Section> buildSections(
        String persona, String profile, List<String> memories, List<String> history, String currentTurn) {

        List<Section> sections = new ArrayList<>(5);
        addSection(sections, PERSONA_HEADER, persona, SectionKind.CONFIGURATION);
        addSection(sections, PROFILE_HEADER, profile, SectionKind.CONFIGURATION);
        addSection(sections, MEMORY_HEADER, join(memories), SectionKind.RECALLABLE);
        addSection(sections, HISTORY_HEADER, join(history), SectionKind.HISTORY);
        addSection(sections, CURRENT_TURN_HEADER,
            currentTurn == null ? "" : currentTurn.trim(), SectionKind.CURRENT);
        return sections;
    }

    /**
     * 追加一个非空段落。
     *
     * @param sections 段落列表
     * @param header   段落标题
     * @param content  段落内容
     * @param kind     段落类别
     */
    private void addSection(List<Section> sections, String header, String content, SectionKind kind) {
        if (content == null || content.isBlank()) {
            return;
        }
        sections.add(new Section(header, content.trim(), kind));
    }

    /**
     * 截断超预算的上下文。
     *
     * @param sections 原始段落
     * @return 截断后的上下文
     */
    private AssembledContext truncate(List<Section> sections) {
        List<Section> kept = new ArrayList<>(sections);
        List<String> dropped = new ArrayList<>();

        // 第一步：牺牲长期记忆。
        removeByKind(kept, dropped, SectionKind.RECALLABLE);
        String candidate = render(kept);
        if (candidate.length() <= budget) {
            return new AssembledContext(candidate, List.copyOf(dropped), candidate.length(), budget);
        }

        // 第二步：逐步丢弃最早的短期历史。
        for (int keep = countKind(kept, SectionKind.HISTORY) - 1; keep >= 0; keep--) {
            List<Section> attempt = new ArrayList<>(kept);
            trimHistory(attempt, keep);
            candidate = render(attempt);
            if (candidate.length() <= budget) {
                return new AssembledContext(candidate, List.copyOf(dropped), candidate.length(), budget);
            }
        }
        removeByKind(kept, dropped, SectionKind.HISTORY);

        // 第三步：配置部分原则上不牺牲。只有它们本身就超预算时才截断，
        // 并把被截断的段落明确标记出来 —— 静默丢弃配置会让模型"忘记自己是谁"。
        //
        // 关键：当前轮在渲染文本的**末尾**，直接对全文做硬截断会把当前轮切掉 ——
        // 那恰恰是最不能丢的部分。因此这里必须先给当前轮留出位置，
        // 再去裁剪配置部分。
        String currentSection = extractSection(kept, SectionKind.CURRENT);
        String configText = renderWithout(kept, SectionKind.CURRENT);
        int reserved = currentSection.isEmpty() ? 0 : currentSection.length() + SECTION_SEPARATOR.length();
        int configBudget = Math.max(0, budget - reserved);
        String clippedConfig = configText.length() > configBudget
            ? configText.substring(0, configBudget)
            : configText;

        String result = currentSection.isEmpty()
            ? clippedConfig
            : clippedConfig + SECTION_SEPARATOR + currentSection;
        dropped.add(PERSONA_HEADER);
        dropped.add(PROFILE_HEADER);
        return new AssembledContext(result, List.copyOf(dropped), result.length(), budget);
    }

    /**
     * 取出指定类别的段落渲染文本。
     *
     * @param sections 段落列表
     * @param kind     类别
     * @return 渲染文本；无该类别段落时返回空字符串
     */
    private String extractSection(List<Section> sections, SectionKind kind) {
        List<Section> filtered = new ArrayList<>();
        for (Section section : sections) {
            if (section.kind() == kind) {
                filtered.add(section);
            }
        }
        return render(filtered);
    }

    /**
     * 渲染除指定类别以外的全部段落。
     *
     * @param sections 段落列表
     * @param kind     要排除的类别
     * @return 渲染文本
     */
    private String renderWithout(List<Section> sections, SectionKind kind) {
        List<Section> filtered = new ArrayList<>();
        for (Section section : sections) {
            if (section.kind() != kind) {
                filtered.add(section);
            }
        }
        return render(filtered);
    }

    /**
     * 移除指定类别的全部段落。
     *
     * @param sections 段落列表
     * @param dropped  已丢弃段落标题的收集器
     * @param kind     要移除的类别
     */
    private void removeByKind(List<Section> sections, List<String> dropped, SectionKind kind) {
        sections.removeIf(section -> {
            if (section.kind() == kind) {
                dropped.add(section.header());
                return true;
            }
            return false;
        });
    }

    /**
     * 统计指定类别的段落数量。
     *
     * @param sections 段落列表
     * @param kind     类别
     * @return 数量
     */
    private int countKind(List<Section> sections, SectionKind kind) {
        int count = 0;
        for (Section section : sections) {
            if (section.kind() == kind) {
                count++;
            }
        }
        return count;
    }

    /**
     * 只保留最近的若干条短期历史。
     *
     * @param sections 段落列表
     * @param keep     保留的行数
     */
    private void trimHistory(List<Section> sections, int keep) {
        for (int index = 0; index < sections.size(); index++) {
            Section section = sections.get(index);
            if (section.kind() != SectionKind.HISTORY) {
                continue;
            }
            String[] lines = section.content().split("\n");
            int from = Math.max(0, lines.length - keep);
            StringBuilder builder = new StringBuilder();
            for (int line = from; line < lines.length; line++) {
                if (!builder.isEmpty()) {
                    builder.append('\n');
                }
                builder.append(lines[line]);
            }
            sections.set(index, new Section(section.header(), builder.toString(), section.kind()));
        }
    }

    /**
     * 把段落渲染成最终文本。
     *
     * @param sections 段落列表
     * @return 渲染结果
     */
    private String render(List<Section> sections) {
        StringBuilder builder = new StringBuilder();
        for (Section section : sections) {
            if (section.content().isBlank()) {
                continue;
            }
            if (!builder.isEmpty()) {
                builder.append(SECTION_SEPARATOR);
            }
            builder.append(section.header()).append('\n').append(section.content());
        }
        return builder.toString();
    }

    /**
     * 把列表拼成多行文本。
     *
     * @param items 条目列表
     * @return 拼接后的文本；列表为空时返回空字符串
     */
    private String join(List<String> items) {
        if (items == null || items.isEmpty()) {
            return "";
        }
        StringBuilder builder = new StringBuilder();
        for (String item : items) {
            if (item == null || item.isBlank()) {
                continue;
            }
            if (!builder.isEmpty()) {
                builder.append('\n');
            }
            builder.append(item.trim());
        }
        return builder.toString();
    }

    /** 段落类别。 */
    private enum SectionKind {

        /** 配置部分（人设、画像）：原则上不牺牲。 */
        CONFIGURATION,

        /** 可再召回的资料（长期记忆）：超预算时最先牺牲。 */
        RECALLABLE,

        /** 短期历史：超预算时逐步丢弃较早的部分。 */
        HISTORY,

        /** 当前轮：永不牺牲。 */
        CURRENT
    }

    /**
     * 一个上下文段落。
     *
     * @param header  段落标题
     * @param content 段落内容
     * @param kind    段落类别
     */
    private record Section(String header, String content, SectionKind kind) {
    }

    /**
     * 装配结果。
     *
     * @param context        装配后的上下文
     * @param droppedSections 被丢弃的段落标题
     * @param length         上下文长度
     * @param budget         预算上限
     */
    public record AssembledContext(
        String context, List<String> droppedSections, int length, int budget) {

        /**
         * 判断是否发生了截断。
         *
         * @return 存在被丢弃的段落返回 {@code true}
         */
        public boolean truncated() {
            return !droppedSections.isEmpty();
        }
    }
}
