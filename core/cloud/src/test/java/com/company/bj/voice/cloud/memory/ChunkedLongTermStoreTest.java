package com.company.bj.voice.cloud.memory;

import static org.assertj.core.api.Assertions.assertThat;

import com.company.bj.voice.cloud.chroma.ChromaClient;
import com.company.bj.voice.cloud.config.ChromaProperties;
import com.company.bj.voice.cloud.config.EmbeddingProperties;
import com.company.bj.voice.cloud.embed.LocalEmbeddingService;
import com.company.bj.voice.cloud.memory.companion.MemoryChunkSplitter;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.net.http.HttpClient;
import java.util.List;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

/**
 * 分片写入的<b>存储语义</b>验证。
 *
 * <p>验证的是服务端行为（作用域过滤、软删除、父子关系），
 * 因此与 {@link LongTermStoreTest} 一样直连<b>真实本地 Chroma 服务</b>。
 *
 * <p><b>为什么不用桩嵌入</b>：分片的核心价值在于"问句只需与其中一个片段相近"。
 * 桩嵌入是词面哈希，答不出这个问题 —— 桩能证明的只有"存了几条、能不能删掉"，
 * 而那部分用真实嵌入同样能覆盖。多引入一个桩只会掩盖真实缺陷。
 *
 * <p><b>外部依赖</b>：需要本地 Chroma（8765）与本地嵌入服务（8766）在跑。
 * 嵌入服务不可用时用例会失败而不是静默跳过 —— 静默跳过会让分片路径
 * 在 CI 上"看起来一直是绿的"，实际从未被验证过。
 *
 * <p><b>集合选择</b>：用专用集合 {@code it_mem_chunked}，
 * 不与知识库集合、{@code it_mem_longterm} 共用。
 */
@EnabledIfEnvironmentVariable(named = "CHROMA_IT", matches = "true")
class ChunkedLongTermStoreTest {

    /** 冒烟测试专用集合名，满足 3-512 长度与 [a-zA-Z0-9._-] 字符集规则。 */
    private static final String COLLECTION_NAME = "it_mem_chunked";

    /** 用于测试的长记忆：真实对话里用户会说的完整句子。 */
    private static final String LONG_MEMORY =
        "我妈妈叫李芳，她很爱我，每天都给我做饭，还总提醒我早点休息";

    private ScopeResolver resolver;
    private ChromaLongTermStore store;
    private MemoryScope scope;

    @BeforeEach
    void 准备集合与作用域() {
        ChromaProperties props = new ChromaProperties();
        props.setTenant("default_tenant");
        props.setDatabase("default_database");
        props.setMemoryCollection(COLLECTION_NAME);

        EmbeddingProperties embeddingProps = new EmbeddingProperties();
        ChromaClient client =
            new ChromaClient(props, HttpClient.newHttpClient(), new ObjectMapper());
        resolver = new ScopeResolver();
        store = new ChromaLongTermStore(client, new LocalEmbeddingService(embeddingProps),
            props, resolver, new MemoryChunkSplitter());
        // 每次运行使用唯一作用域，避免不同运行之间互相检索到对方的记录。
        scope = MemoryScope.of("tenant-" + UUID.randomUUID(), "owner-" + UUID.randomUUID());
    }

    @Test
    @DisplayName("长记忆写入后能按父标识读回完整正文")
    void 长记忆按父标识读回完整正文() {
        MemoryRecord recorded = resolver.withScopeResult(scope, () -> store.remember(LONG_MEMORY));

        // 返回的必须是父记忆的正文，不是某个片段。
        assertThat(recorded.content()).isEqualTo(LONG_MEMORY);

        MemoryRecord found = resolver.withScopeResult(scope, () -> store.find(recorded.id()))
            .orElseThrow();
        assertThat(found.content()).isEqualTo(LONG_MEMORY);
        assertThat(found.id()).isEqualTo(recorded.id());
    }

    @Test
    @DisplayName("短记忆不分片，结构与历史数据一致")
    void 短记忆不分片() {
        MemoryRecord recorded = resolver.withScopeResult(scope, () -> store.remember("我妈妈叫李芳"));

        // 短记忆只有一条记录，列举时只出现一次。
        List<MemoryRecord> listed = resolver.withScopeResult(scope, () -> store.list(10));
        assertThat(listed).extracting(MemoryRecord::id).containsExactly(recorded.id());
    }

    @Test
    @DisplayName("长记忆列举时按父记忆去重，不重复显示片段")
    void 长记忆列举去重() {
        MemoryRecord recorded = resolver.withScopeResult(scope, () -> store.remember(LONG_MEMORY));

        List<MemoryRecord> listed = resolver.withScopeResult(scope, () -> store.list(20));

        // 片段有多条，但列举只应出现一次父记忆。
        assertThat(listed).extracting(MemoryRecord::id).containsExactly(recorded.id());
        assertThat(listed).extracting(MemoryRecord::content).containsExactly(LONG_MEMORY);
    }

    @Test
    @DisplayName("遗忘长记忆会连带归档全部片段")
    void 遗忘连带归档片段() {
        MemoryRecord recorded = resolver.withScopeResult(scope, () -> store.remember(LONG_MEMORY));

        boolean forgotten = resolver.withScopeResult(scope, () -> store.forget(recorded.id()));
        assertThat(forgotten).isTrue();

        // 片段必须全部归档 —— 只归档一个的话，其余片段会继续被召回，
        // 用户会看到"已删除的记忆"又冒出来。
        List<MemoryRecord> live = resolver.withScopeResult(scope, () -> store.list(20));
        assertThat(live).extracting(MemoryRecord::id).doesNotContain(recorded.id());

        List<MemoryRecord> archived = resolver.withScopeResult(scope, () -> store.archived(20));
        assertThat(archived).extracting(MemoryRecord::id).contains(recorded.id());
    }

    @Test
    @DisplayName("检索命中片段时，引用来源指向父记忆而非片段")
    void 检索命中片段时引用父记忆() {
        MemoryRecord recorded = resolver.withScopeResult(scope, () -> store.remember(LONG_MEMORY));

        // 用只有首个子句能命中的问句检索。
        List<ScoredMemoryRecord> hits = resolver.withScopeResult(
            scope, () -> store.searchScored("我妈妈叫什么", 5));

        assertThat(hits).isNotEmpty();
        ScoredMemoryRecord top = hits.get(0);
        // 引用来源必须是父记忆的 id —— 否则用户会看到一条自己没说过的话。
        assertThat(top.id()).isEqualTo(recorded.id());
        // 正文也必须是完整记忆，而不是片段。
        assertThat(top.content()).isEqualTo(LONG_MEMORY);
    }

    @Test
    @DisplayName("同一记忆的多个片段只召回一次")
    void 多片段只召回一次() {
        resolver.withScopeResult(scope, () -> store.remember(LONG_MEMORY));

        List<ScoredMemoryRecord> hits = resolver.withScopeResult(
            scope, () -> store.searchScored("我妈妈叫什么", 20));

        // 若不去重，同一记忆的多个片段会占满召回窗口，把其他记忆挤出去。
        assertThat(hits).extracting(ScoredMemoryRecord::id).doesNotHaveDuplicates();
    }

    @Test
    @DisplayName("跨作用域仍不可见分片")
    void 跨作用域不可见分片() {
        resolver.withScopeResult(scope, () -> store.remember(LONG_MEMORY));

        List<ScoredMemoryRecord> hits = resolver.withScopeResult(
            MemoryScope.of(scope.tenantId(), "other-owner"),
            () -> store.searchScored("我妈妈叫什么", 10));

        assertThat(hits).isEmpty();
    }
}
