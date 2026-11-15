package com.company.bj.voice.cloud.agent;

import com.company.bj.voice.cloud.memory.companion.CompanionMemoryCategory;
import com.company.bj.voice.cloud.memory.companion.CompanionMemoryClassifier;
import com.company.bj.voice.cloud.memory.companion.MemoryUpdateService;
import java.util.List;

/**
 * 记忆写入子智能体。
 *
 * <p>负责从用户话语里判断"哪些内容值得记住"，并写入长期记忆。
 *
 * <p><b>记忆写入子智能体不产生用户可见的回复</b>：
 * 它是<b>副作用型</b>处理器，输出为空回复，优先级最低 ——
 * 用户的这一轮同时触发了"播放音乐"和"记住我喜欢音乐"时，
 * 该下发的是播放音乐的应答，而不是"我记住你了"。
 */
public class MemoryWriteSubAgent implements SubAgentHandler {

    /** 记忆写入子智能体的优先级。最低。 */
    public static final int PRIORITY = SubAgentArbitrator.PRIORITY_EMOTION + 10;

    /** 记忆写入类意图。 */
    public static final String INTENT_MEMORY_WRITE = "memory_write";

    /** 记忆分类器。 */
    private final CompanionMemoryClassifier classifier;

    /** 记忆更新服务。 */
    private final MemoryUpdateService updateService;

    /**
     * 构造记忆写入子智能体。
     *
     * @param classifier   记忆分类器
     * @param updateService 记忆更新服务
     */
    public MemoryWriteSubAgent(
        CompanionMemoryClassifier classifier, MemoryUpdateService updateService) {
        this.classifier = classifier;
        this.updateService = updateService;
    }

    @Override
    public SubAgentResult handle(SubAgentRequest request) {
        CompanionMemoryCategory category = classifier.classify(request.text());
        if (!category.longTerm()) {
            // 只有长期类才写入；情景类与不入库类直接跳过。
            return SubAgentResult.of("", request.intent(), "neutral");
        }

        updateService.upsert(request.text());
        return SubAgentResult.of("", request.intent(), "neutral");
    }

    @Override
    public List<String> supportedIntents() {
        return List.of(INTENT_MEMORY_WRITE);
    }

    @Override
    public int priority() {
        return PRIORITY;
    }
}
