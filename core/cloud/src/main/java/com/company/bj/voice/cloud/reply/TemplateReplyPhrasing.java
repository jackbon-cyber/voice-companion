package com.company.bj.voice.cloud.reply;

/**
 * 模板式措辞生成器 —— 默认实现。
 *
 * <p>把记忆内容套进固定句式，产出行为完全确定的回复。
 *
 * <p><b>为什么默认用模板而不是大模型</b>：
 * <ul>
 *   <li><b>可离线</b>：不依赖任何外部服务，"克隆下来就能跑"是本作品的第一目标；</li>
 *   <li><b>行为可判定</b>：端到端断言可以直接比对回复正文是否包含记忆内容。
 *       大模型生成的措辞不确定，断言只能退化成"检查引用来源"，覆盖面会变窄；</li>
 *   <li><b>零延迟与零成本</b>：陪伴场景的首包延迟预算很紧（见方案 §9.1）。</li>
 * </ul>
 *
 * <p>代价是措辞生硬。接入大模型后，记忆的<b>选择</b>仍然由准入策略决定，
 * 大模型只负责把选中的那一条说得更自然 —— 因此不会引入编造风险。
 */
public class TemplateReplyPhrasing implements ReplyPhrasing {

    /** 记起时的回复模板。 */
    private static final String RECALL_TEMPLATE = "我记得，%s";

    /**
     * 把记忆内容套进模板。
     *
     * @param memoryContent 命中的记忆内容
     * @return 回复正文
     */
    @Override
    public String phrase(String memoryContent) {
        return String.format(RECALL_TEMPLATE, memoryContent);
    }
}
