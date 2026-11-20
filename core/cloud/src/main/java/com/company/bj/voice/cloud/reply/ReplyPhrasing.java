package com.company.bj.voice.cloud.reply;

/**
 * 回复措辞生成端口。
 *
 * <p><b>为什么要有这个端口</b>：回复正文有两种来源 ——
 * 模板（离线可用、行为完全确定）与大模型（表达自然）。
 * 把二者抽象成一个端口后，调用方只依赖"给我一条措辞"这件事，
 * 新增第三种来源时不需要改动调用方，也不需要在既有方法里堆
 * {@code if (llmEnabled)} 分支。
 *
 * <p><b>这个端口不产出引用来源</b>：引用来源（{@code citations}）
 * 永远由记忆准入层决定，见 {@link MemoryGroundedReplyService}。
 */
public interface ReplyPhrasing {

    /**
     * 把一条记忆内容表述成回复正文。
     *
     * @param memoryContent 命中的记忆内容
     * @return 回复正文；不可用时返回空字符串
     */
    String phrase(String memoryContent);
}
