package com.company.bj.voice.cloud.memory.companion;

import java.util.ArrayList;
import java.util.List;

/**
 * 把一条记忆切成若干<b>检索片段</b>。
 *
 * <p><b>要解决的问题（实测得出）</b>：
 * 用户在真实对话里说的是完整句子，
 * 例如"我妈妈叫李芳，她很爱我，每天都给我做饭，还总提醒我早点休息"。
 * 整句嵌入时，问句"我妈妈叫什么"与这句话的向量相距较远，
 * 得分落到相关性下限以下 → 机器人对**刚刚听用户说过的事**回答"没有记录"。
 *
 * <p>实测数据（本地嵌入服务 + 真实语料）：
 * <pre>
 *   整句嵌入：这条长记忆的得分 = 0.5145  → 低于下限 0.529 → 被误拒
 *   分片嵌入：命中片段"我妈妈叫李芳"的得分 = 0.6176 → 通过
 * </pre>
 * 留出集上（13 条可答 + 13 条无答案），整句嵌入答错 6 条、分片嵌入答错 1 条。
 *
 * <p><b>为什么按中文标点切</b>：中文的并列信息天然以逗号分隔
 * （"我妈妈叫李芳，她很爱我，每天都给我做饭"），
 * 每个子句承载一个独立事实，问句只会命中其中最相关的那一个。
 *
 * <p><b>分片不是免费的</b>，它带来两个代价，必须如实说明：
 * <ol>
 *   <li><b>片段级语义区分变弱</b> —— 实测留出集上唯一的错例是
 *       问句"我眼下在忙着准备哪件事"命中了片段"我表姐在南京工作"。
 *       片段比整句短，与问句的语义距离天然更近；</li>
 *   <li><b>存储量翻倍</b> —— 一条记忆变成多条记录。
 *       通过"父记录 id"元数据把它们绑在一起，召回时按父聚合。</li>
 * </ol>
 *
 * <p><b>为什么不做更细的切分</b>（按字数/按标点全切）：
 * 切得越细，片段越短、得分越高，但片段越可能失去可独立陈述的语义
 * （"还总提醒我早点休息" 单独拿出来不是一条记忆）。
 * 按标点切得到的片段通常仍是一个完整的事实句，这是可接受的边界。
 */
public class MemoryChunkSplitter {

    /** 分隔符。中文标点在前，英文在后。 */
    private static final String[] SEPARATORS = {"，", ",", "、", "；", ";"};

    /** 片段最短长度。太短的片段缺乏独立语义，检索时只会带来噪声。 */
    private static final int MIN_CHUNK_LENGTH = 3;

    /** 无需分片的长度上限：短句整体就是一个片段，拆开反而破坏语义。 */
    private static final int MAX_SINGLE_CHUNK_LENGTH = 12;

    /**
     * 把一条记忆切成检索片段。
     *
     * <p><b>切不出多个片段时返回原句</b>（含在列表里）——
     * 短记忆不需要分片，强行切反而会让片段失去语义。
     *
     * @param content 记忆内容
     * @return 片段列表；内容为空时返回空列表
     */
    public List<String> split(String content) {
        if (content == null || content.isBlank()) {
            return List.of();
        }
        String trimmed = content.trim();

        // 短句整体作为一个片段。
        if (trimmed.length() <= MAX_SINGLE_CHUNK_LENGTH) {
            return List.of(trimmed);
        }

        List<String> chunks = new ArrayList<>();
        for (String clause : splitBySeparators(trimmed)) {
            if (clause.length() >= MIN_CHUNK_LENGTH) {
                chunks.add(clause);
            }
        }

        // 切完只剩一片（或切不动）时，用原句 —— 分片必须至少保留语义完整。
        if (chunks.size() <= 1) {
            return List.of(trimmed);
        }
        return chunks;
    }

    /**
     * 按分隔符把文本切成子句。
     *
     * @param text 文本
     * @return 子句列表
     */
    private List<String> splitBySeparators(String text) {
        List<String> parts = new ArrayList<>();
        parts.add(text);
        for (String separator : SEPARATORS) {
            List<String> expanded = new ArrayList<>(parts.size());
            for (String part : parts) {
                for (String piece : part.split(java.util.regex.Pattern.quote(separator))) {
                    expanded.add(piece);
                }
            }
            parts = expanded;
        }
        List<String> result = new ArrayList<>(parts.size());
        for (String part : parts) {
            String trimmed = part.trim();
            if (!trimmed.isEmpty()) {
                result.add(trimmed);
            }
        }
        return result;
    }
}
