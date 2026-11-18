package com.company.bj.voice.cloud.memory.spi;

import com.company.bj.voice.cloud.memory.LongTermStore;
import com.company.bj.voice.cloud.memory.MemoryRecord;
import com.company.bj.voice.cloud.memory.MemoryScope;
import com.company.bj.voice.cloud.memory.ScopeResolver;
import com.company.bj.voice.cloud.memory.companion.ScopedCompanionMemoryStore;
import io.agentscope.core.memory.LongTermMemory;
import io.agentscope.core.message.Msg;
import java.util.List;
import reactor.core.publisher.Mono;

/**
 * 记忆存储到 AgentScope 记忆契约的适配器。
 *
 * <p>把本工程复制的记忆层适配成 AgentScope 的 {@link LongTermMemory} 契约，
 * 使多智能体编排能够直接复用同一份记忆，而不必为 AgentScope 另建一套存储。
 *
 * <p><b>为什么不让 AgentScope 直接依赖存储实现</b>：
 * AgentScope 的契约是"给一组消息、记住它们"与"给一条消息、召回相关内容"，
 * 粒度比陪伴场景的记忆分类（关系事实 / 稳定偏好 / 时效事件 / 情景 …）粗。
 * 直接对接会丢掉分类信息，而分类是陪伴记忆召回质量的核心。
 * 因此本类只承担<b>契约转换</b>，分类与冲突消解仍在记忆层内完成。
 *
 * <p><b>作用域隔离不被适配器削弱</b>：
 * 本适配器<b>刻意不提供</b>按指定作用域查询的路径 ——
 * 越权读取返回空，而不是抛异常，更不是返回别人的记忆。
 * 隔离由 {@link ScopedCompanionMemoryStore} 在存储层强制，
 * 本类再按作用域复核一次（纵深防御）：
 * 存储换实现、或某条路径漏了过滤时，隔离不会因此失效。
 */
public class MemoryServiceAdapter implements LongTermMemory {

    /** 召回时返回给 AgentScope 的文本条数上限。 */
    private static final int DEFAULT_TOP_K = 5;

    /** 长期记忆存储端口。 */
    private final LongTermStore longTermStore;

    /** 作用域解析器。 */
    private final ScopeResolver scopeResolver;

    /**
     * 构造适配器。
     *
     * @param longTermStore 长期记忆存储，不能为 null
     * @param scopeResolver 作用域解析器，不能为 null
     * @throws IllegalArgumentException 参数为 null 时抛出
     */
    public MemoryServiceAdapter(LongTermStore longTermStore, ScopeResolver scopeResolver) {
        if (longTermStore == null) {
            throw new IllegalArgumentException("longTermStore must not be null");
        }
        if (scopeResolver == null) {
            throw new IllegalArgumentException("scopeResolver must not be null");
        }
        this.longTermStore = longTermStore;
        this.scopeResolver = scopeResolver;
    }

    /**
     * 记录一组消息到长期记忆。
     *
     * <p>每条消息的<b>文本内容</b>单独写入一条记忆。
     * 消息列表通常包含"用户说了什么"与"系统回了一句"两类，
     * 把它们合并成一条会让召回结果里混入模型自己的话。
     *
     * @param messages 待记录的消息列表
     * @return 完成信号
     * @throws IllegalStateException 当前没有活动作用域时抛出
     */
    @Override
    public Mono<Void> record(List<Msg> messages) {
        return Mono.fromRunnable(() -> {
            // 先解析作用域：拒绝"无活动作用域"这件事必须由适配器自己负责，
            // 不能指望底层存储恰好也做了同样的检查 ——
            // 存储换实现、或者存储的某条路径漏了检查，隔离就失效了。
            scopeResolver.current();
            if (messages == null || messages.isEmpty()) {
                return;
            }
            for (Msg message : messages) {
                String text = extractText(message);
                if (text == null || text.isBlank()) {
                    continue;
                }
                longTermStore.remember(text);
            }
        });
    }

    /**
     * 按查询消息召回相关的长期记忆。
     *
     * @param query 查询消息
     * @return 召回文本；无命中时为空串
     * @throws IllegalStateException 当前没有活动作用域时抛出
     */
    @Override
    public Mono<String> retrieve(Msg query) {
        return Mono.fromSupplier(() -> {
            // 与 record 同样的理由：作用域的缺失必须在适配器层被拒绝。
            scopeResolver.current();
            String text = extractText(query);
            if (text == null || text.isBlank()) {
                return "";
            }
            List<MemoryRecord> candidates = longTermStore.search(text, DEFAULT_TOP_K);
            StringBuilder builder = new StringBuilder();
            for (MemoryRecord record : candidates) {
                // 纵深防御：即便底层存储漏了作用域过滤，这里也会把越权记录剔除。
                if (!isOwnedByCurrentScope(record)) {
                    continue;
                }
                if (!builder.isEmpty()) {
                    builder.append('\n');
                }
                builder.append(record.content());
            }
            return builder.toString();
        });
    }

    /**
     * 判断一条记录是否归属当前作用域。
     *
     * <p>归档记录一律视为不可见：归档是软删除，
     * 被召回的归档记录等于"删除没生效"。
     *
     * @param record 待判断的记录
     * @return 归属当前作用域且未归档时为 true
     */
    private boolean isOwnedByCurrentScope(MemoryRecord record) {
        if (record == null || record.archived()) {
            return false;
        }
        MemoryScope scope = scopeResolver.current();
        return scope.equals(record.scope());
    }

    /**
     * 取出消息的文本内容。
     *
     * @param message 消息
     * @return 文本内容；消息为 null 或无文本时返回 null
     */
    private static String extractText(Msg message) {
        if (message == null) {
            return null;
        }
        return message.getTextContent();
    }
}
