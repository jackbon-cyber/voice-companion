package com.company.bj.voice.cloud.agent;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * 子智能体处理器注册表。
 *
 * <p>按意图把请求路由到对应的处理器。新增一个处理器只需<b>注册</b>，
 * 主流程一行都不用改 —— 这是架构守则 A3 要求的扩展点形态。
 *
 * <p><b>同一意图注册多个处理器时的取舍</b>：取<b>优先级数值最小</b>的那个。
 * 优先级数值越小越优先（如安全 10 < 事实 20 < 人设 30 < 情绪 40），
 * 这样"安全优先"这类规则落在<b>注册数据</b>里，而不是散落在路由代码的 if 分支里。
 */
public class SubAgentRegistry {

    /** 意图标识到处理器的映射。 */
    private final Map<String, SubAgentHandler> handlers = new LinkedHashMap<>();

    /** 按优先级排序的处理器列表，用于裁决。 */
    private final List<SubAgentHandler> ordered = new ArrayList<>();

    /**
     * 注册一个处理器。
     *
     * <p>同一意图重复注册时<b>后者覆盖前者</b>，
     * 且不会在映射里留下重复键。
     *
     * @param handler 处理器
     * @return 注册表自身，便于链式调用
     */
    public SubAgentRegistry register(SubAgentHandler handler) {
        if (handler == null) {
            throw new IllegalArgumentException("sub agent handler must not be null");
        }
        for (String intent : handler.supportedIntents()) {
            handlers.put(intent, handler);
        }
        ordered.add(handler);
        ordered.sort((left, right) -> Integer.compare(left.priority(), right.priority()));
        return this;
    }

    /**
     * 查找负责某意图的处理器。
     *
     * @param intent 意图标识
     * @return 处理器；未注册时为空
     */
    public Optional<SubAgentHandler> find(String intent) {
        if (intent == null) {
            return Optional.empty();
        }
        return Optional.ofNullable(handlers.get(intent));
    }

    /**
     * 列出全部已注册的处理器，按优先级升序。
     *
     * @return 处理器列表
     */
    public List<SubAgentHandler> handlers() {
        return List.copyOf(ordered);
    }

    /**
     * 列出已注册处理器负责的全部意图。
     *
     * @return 意图标识集合
     */
    public java.util.Set<String> registeredIntents() {
        return java.util.Set.copyOf(handlers.keySet());
    }
}
