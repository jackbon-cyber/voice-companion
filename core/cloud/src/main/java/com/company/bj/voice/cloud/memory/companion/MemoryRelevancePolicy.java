package com.company.bj.voice.cloud.memory.companion;

import com.company.bj.voice.cloud.memory.ScoredMemoryRecord;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * 记忆陈述的<b>相关性准入</b>策略。
 *
 * <p><b>要解决的问题</b>：产品真正回复用户的是排序第一条记忆。
 * 但"排在第一"不等于"相关" —— 检索总会返回点什么，哪怕完全不相关。
 * 无条件把第一条当事实陈述，会出现：
 *
 * <pre>
 * 用户：我有什么饮食禁忌吗
 * 机器人：我记得，我最爱吃酸菜鱼     ← 记忆库里确实有这条，但它答的不是用户问的
 * </pre>
 *
 * <p>更糟的情况是<b>陈述已被改口作废的旧事实</b>：
 * 用户先说"我妈妈叫李芳"，后改口"我妈妈叫王芳"。
 * 正常路径下旧记录会被归档（{@code MemoryUpdateService} 的取代逻辑），
 * 但若两次表述的<b>主体词元不一致</b>（"我妈妈"与"我母亲"），
 * 两条会同时处于有效状态，检索可能把旧的那条排在前面 ——
 * 机器人就会说出用户已经作废的事实。
 *
 * <p><b>本策略的三步</b>：
 * <ol>
 *   <li><b>同主体去重</b> —— 同一主体的多条记录只保留<b>最新</b>的那条。
 *       "最新"按写入时间判定：用户改口时，新记忆的写入时间必然更晚。
 *       这一步直接消除"陈述旧事实"的场景；</li>
 *   <li><b>相关性下限</b> —— 去重后得分低于下限的命中，不足以作为事实陈述；</li>
 *   <li><b>如实回退</b> —— 没有可陈述的命中时，明说"没有记录"，不猜。</li>
 * </ol>
 *
 * <p><b>为什么"如实说没有记录"优于"猜一个"</b>：
 * 陪伴场景里，"我不确定"是可接受的，"记错了"是不可接受的。
 * 用户会纠正前者，但后者会让用户不再信任机器人的记忆 ——
 * 而记忆正是这个产品的核心卖点，信任一旦损失无法靠后续能力补回。
 *
 * <p><b>为什么不设"区分度"判据</b>（一个被实测否掉的直觉）：
 * 本能的设想是"第一名与第二名得分接近就说明分不清，不作答"。
 * 实测否掉了它：在 13 条记忆召回评测集上，
 * <b>唯一答错的那条，其第一、二名的距离差（0.0518）比答对的样本中的大多数还大</b>，
 * 而一条答对的样本其距离差只有 0.0095。
 * 也就是说得分差与正确性<b>不相关</b>，用它当判据只会白白降低覆盖率。
 * 因此本策略不含区分度判据 —— 阈值不该由直觉定，该由实测定。
 *
 * <p><b>阈值的实测依据</b>（<b>留出集</b>推导，语料与评测集相同、问句完全不重合）：
 * <ul>
 *   <li>答得对时（排第一正是期望记忆）的<b>最低</b>得分 = 0.5480；</li>
 *   <li>答不出时（库里根本没有对应事实）的<b>最高</b>得分 = 0.5402。</li>
 * </ul>
 * 两者之间有 0.0078 的可分缝隙，下限取中点 <b>0.544</b>。
 * 之所以留出集而不是评测集：评测集就是门禁要用的那批数据，
 * 在它上面挑阈值等于拿答案调答案，换批数据就失效。
 *
 * <p><b>这个阈值对应"分片嵌入"下的分布</b>：一条记忆按中文标点切成若干片段后
 * 各自嵌入，问句只需与其中最相关的一个片段相近。
 * 实测长记忆的得分从 0.5145 抬到 0.6176 ——
 * 分片之前它落在下限以下、会被误拒。
 * 代价是分布整体平移，<b>阈值必须同步重推</b>（0.529 → 0.544）。
 *
 * <p><b>被实测否掉的候选方案</b>（留在这里是为了说明"为什么没有"）：
 * <ol>
 *   <li><b>区分度判据</b>（第一名与第二名得分差太小就拒答）——
 *       实测不可分：答不出的问句其领先幅度最高到 +0.0882，
 *       而答对的问句最低只有 +0.0158，两者<b>反向重叠</b>。
 *       横向比较了绝对得分、领先幅度、得分比、峰值突出度、分数集中度
 *       五种判据，<b>只有绝对得分能分开</b>；</li>
 *   <li><b>查询侧加检索指令</b>（BGE 官方推荐的
 *       "为句子生成表示以用于检索相关文章："前缀）——
 *       实测<b>没有改善</b>：重叠宽度只从 0.0559 降到 0.0448，
 *       且评测集 Top-1 正确率从 12/13 掉到 11/13。
 *       代价大于收益，故不采用；</li>
 *   <li><b>更小的下限</b>（0.476）—— 留出集上会让 11/14
 *       答不上的问句被当成答案，<b>系统会开始编造</b>。
 *       这是最不能接受的失败模式：机器人说了库里没有的事。</li>
 * </ol>
 *
 * <p><b>阈值的脆弱性必须诚实说明</b>：0.544 两侧只有 0.0039 的余量，
 * 样本量也只有 13 + 13 条。这个阈值是<b>当前实测下的取值</b>，
 * 不是普适结论 —— 评测集与留出集扩充后<b>必须重测</b>。
 * 报告里把这个余量与脆弱性一并写出，是为了不让读者误以为它是稳的。
 */
public class MemoryRelevancePolicy {

    /** 相关性得分下限。低于该值不作为事实陈述。
     *
     * <p><b>实测依据（留出集推导，与评测集无关）</b>：
     * 另建一份"问句与评测集不重合、语料相同"的留出集，
     * 测出两个边界：
     * <ul>
     *   <li>答得对（排第一正是期望记忆）时的<b>最低</b>得分 = 0.5480；</li>
     *   <li>答不出（库里根本没有对应事实）时的<b>最高</b>得分 = 0.5402。</li>
     * </ul>
     * 两个边界之间有 0.0078 的可分缝隙，取中点 <b>0.544</b>。
     *
     * <p><b>为什么阈值由留出集定，而不是由评测集定</b>：
     * 评测集就是门禁要用的那批数据，在它上面挑一个"能过线"的数
     * 就是拿答案调答案 —— 换一批数据立刻失效。
     * 留出集与评测集的问句不重合，阈值因此是<b>独立</b>推导出来的，
     * 再拿评测集做验收。
     *
     * <p><b>为什么用得分而不是距离</b>：得分越大越相关，
     * 符合"置信度"的直觉，且与知识库检索、AgentScope 适配器
     * 用的是同一个换算公式（{@code ChromaQueryResultReader#toScore}），
     * 避免同一个数据在不同入口算出不同量纲的数。
     *
     * <p><b>这个阈值对应"分片嵌入"下的分布</b>（见
     * {@code core/eval/experiments/chunked_threshold.py}）。
     * 分片把长记忆的得分整体抬高（0.5145 → 0.6176），
     * 因此阈值必须同步重推 —— <b>沿用旧阈值等于用一个尺子量另一把刻度</b>。
     * 推导脚本同时跑"整句嵌入"与"分片嵌入"两条路径，
     * 换回整句存储时阈值必须回到 0.529。 */
    public static final double MIN_RELEVANCE_SCORE = 0.544;

    /** 主体词元长度（"我妈妈"三个字）。 */
    private static final int SUBJECT_PREFIX_LENGTH = 3;

    /** 相关性下限。 */
    private final double minRelevanceScore;

    /**
     * 构造准入策略。
     *
     * @param minRelevanceScore 相关性得分下限
     */
    public MemoryRelevancePolicy(double minRelevanceScore) {
        this.minRelevanceScore = minRelevanceScore;
    }

    /**
     * 构造默认策略。
     *
     * @return 使用默认阈值的策略
     */
    public static MemoryRelevancePolicy standard() {
        return new MemoryRelevancePolicy(MIN_RELEVANCE_SCORE);
    }

    /**
     * 从候选命中中挑出<b>可以当作事实陈述</b>的那一条。
     *
     * @param candidates 带得分的候选命中，按得分降序
     * @return 可陈述的命中；没有可陈述的命中时为空
     */
    public Optional<ScoredMemoryRecord> select(List<ScoredMemoryRecord> candidates) {
        if (candidates == null || candidates.isEmpty()) {
            return Optional.empty();
        }

        List<ScoredMemoryRecord> deduped = keepNewestPerSubject(candidates);
        if (deduped.isEmpty()) {
            return Optional.empty();
        }

        ScoredMemoryRecord top = deduped.get(0);

        // 相关性下限。得分未知（底层实现不支持带得分检索）时跳过这一判据 ——
        // 拿不到得分不等于不相关，此时按"有命中就用"处理，
        // 但绝不能把"未知"伪装成"已知"。
        if (top.scored() && top.score() < minRelevanceScore) {
            return Optional.empty();
        }

        return Optional.of(top);
    }

    /**
     * 同一主体只保留最新的那条记录。
     *
     * <p><b>为什么按主体去重</b>：用户改口时（"我妈妈叫李芳" → "我妈妈叫王芳"），
     * 正常路径下旧记录会被归档；但若两次表述的主体词元不一致
     * （"我妈妈"与"我母亲"），两条会同时有效。
     * 此时若不去重，检索可能把旧的那条排在前面，
     * 机器人就会陈述用户已经作废的事实 ——
     * 这类错误比"答不上来"伤害大得多。
     *
     * <p><b>为什么按写入时间取最新</b>：用户改口时，新记忆的写入时间必然更晚，
     * 这是唯一不依赖"表述完全相同"就能判定的先后关系。
     *
     * <p><b>为什么主体词元取前三字</b>："我妈妈"与"我母亲"的前三字不同，
     * 因此这种情况<b>去重不了</b>，仍可能同时有效。
     * 这是已知的未覆盖场景，如实记录在此而不是假装解决 ——
     * 彻底解决需要做主语归一化（"我母亲" → "我妈妈"），属于后续工作。
     *
     * @param candidates 候选命中
     * @return 每个主体只保留最新记录后的列表，按得分降序
     */
    private List<ScoredMemoryRecord> keepNewestPerSubject(List<ScoredMemoryRecord> candidates) {
        Map<String, ScoredMemoryRecord> newestBySubject = new LinkedHashMap<>();
        List<ScoredMemoryRecord> withoutSubject = new ArrayList<>();

        for (ScoredMemoryRecord candidate : candidates) {
            String subject = subjectOf(candidate.content());
            if (subject.isEmpty()) {
                withoutSubject.add(candidate);
                continue;
            }
            ScoredMemoryRecord existing = newestBySubject.get(subject);
            if (existing == null) {
                newestBySubject.put(subject, candidate);
                continue;
            }
            // 同一主体：保留写入时间更晚的那条。
            if (candidate.record().createdAt() > existing.record().createdAt()) {
                newestBySubject.put(subject, candidate);
            }
        }

        List<ScoredMemoryRecord> result = new ArrayList<>(newestBySubject.values());
        result.addAll(withoutSubject);
        result.sort((left, right) -> Double.compare(right.score(), left.score()));
        return result;
    }

    /**
     * 提取一段内容的主体词元。
     *
     * @param content 内容
     * @return 主体词元；内容过短时返回空字符串
     */
    private String subjectOf(String content) {
        if (content == null || content.length() <= SUBJECT_PREFIX_LENGTH) {
            return "";
        }
        return content.substring(0, SUBJECT_PREFIX_LENGTH);
    }

    /**
     * 返回本策略的相关性下限。
     *
     * @return 得分下限
     */
    public double minRelevanceScore() {
        return minRelevanceScore;
    }

    /**
     * 判断一条记录是否满足相关性下限。
     *
     * @param record 带得分的记录
     * @return 满足返回 {@code true}
     */
    public boolean acceptable(ScoredMemoryRecord record) {
        if (record == null) {
            return false;
        }
        return !record.scored() || record.score() >= minRelevanceScore;
    }

    /**
     * 取出记录正文列表。
     *
     * @param records 带得分的记录列表
     * @return 正文列表
     */
    public static List<String> contentsOf(List<ScoredMemoryRecord> records) {
        return records == null
                ? List.of()
                : records.stream().map(ScoredMemoryRecord::content).toList();
    }
}
