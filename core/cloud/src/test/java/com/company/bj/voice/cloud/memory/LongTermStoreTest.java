package com.company.bj.voice.cloud.memory;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.company.bj.voice.cloud.chroma.ChromaClient;
import com.company.bj.voice.cloud.config.ChromaProperties;
import com.company.bj.voice.cloud.embed.EmbeddingNormalizer;
import com.company.bj.voice.cloud.embed.EmbeddingService;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.net.http.HttpClient;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;

/**
 * 长期记忆存储的行为验证。
 *
 * <p>本测试直接访问<b>真实本地 Chroma 服务</b>（{@code http://localhost:8765}），
 * 验证的是「作用域过滤 + 软删除 + 归并」这套<b>服务端语义</b>，
 * 用内存桩无法覆盖。
 *
 * <p><b>集合选择</b>：使用专用集合 {@code it_mem_longterm}，不与知识库集合共用。
 * Chroma 集合的向量维度在首次写入时绑定且不可变，因此本测试的桩嵌入维度
 * （{@value #STUB_EMBEDDING_DIMENSIONS} 维）必须与写入该集合的其它用例一致。
 *
 * <p><b>幂等性</b>：该 Chroma v2 服务<b>没有集合级删除端点</b>，
 * 集合与其中的记录在测试结束后依然存在。因此：
 * <ul>
 *   <li>每次运行的租户/主体作用域都用<b>随机后缀</b>生成，
 *       不同运行之间不会互相检索到对方的记录；</li>
 *   <li>用例内的断言只针对<b>本次运行</b>写入的记录，
 *       不对集合总条数做绝对断言（除 {@code consolidate} 用例外的清理断言外）。</li>
 * </ul>
 */
@EnabledIfEnvironmentVariable(named = "CHROMA_IT", matches = "true")
class LongTermStoreTest {

    /** 冒烟测试专用集合名，满足 3-512 长度与 [a-zA-Z0-9._-] 字符集规则。 */
    private static final String COLLECTION_NAME = "it_mem_longterm";

    /** 桩嵌入模型的向量维度，与 Chroma 集合维度绑定一致。 */
    private static final int STUB_EMBEDDING_DIMENSIONS = 256;

    /** 写入记录时的默认权重。 */
    private static final double DEFAULT_WEIGHT = 1.0;

    private ScopeResolver resolver;
    private ChromaLongTermStore store;
    private MemoryScope scope;

    @BeforeEach
    void 准备集合与作用域() {
        ChromaProperties props = new ChromaProperties();
        props.setTenant("default_tenant");
        props.setDatabase("default_database");
        props.setMemoryCollection(COLLECTION_NAME);

        ChromaClient client = new ChromaClient(props, HttpClient.newHttpClient(), new ObjectMapper());
        resolver = new ScopeResolver();
        store = new ChromaLongTermStore(client, stubEmbeddings(), props, resolver);
        // 每次运行使用唯一的作用域，避免不同运行之间互相检索到对方的记录
        // （服务端没有集合级删除端点，记录会一直留存）。
        scope = MemoryScope.of("tenant-" + UUID.randomUUID(), "owner-" + UUID.randomUUID());
    }

    @Test
    void 写入后可按标识读取() {
        MemoryRecord recorded = resolver.withScopeResult(scope, () -> store.remember("巡检记录：配电室温度正常"));

        Optional<MemoryRecord> found = resolver.withScopeResult(scope, () -> store.find(recorded.id()));

        assertThat(found).isPresent();
        assertThat(found.get().content()).isEqualTo("巡检记录：配电室温度正常");
        assertThat(found.get().weight()).isEqualTo(DEFAULT_WEIGHT);
        assertThat(found.get().scope()).isEqualTo(scope);
        assertThat(found.get().archived()).isFalse();
        assertThat(found.get().createdAt()).isPositive();
    }

    @Test
    void 写入时可指定权重() {
        MemoryRecord recorded = resolver.withScopeResult(scope, () -> store.remember("高权重记忆", 0.75));

        Optional<MemoryRecord> found = resolver.withScopeResult(scope, () -> store.find(recorded.id()));

        assertThat(found).isPresent();
        assertThat(found.get().weight()).isEqualTo(0.75);
    }

    @Test
    void 遗忘后检索不到但归档可查() {
        MemoryRecord recorded = resolver.withScopeResult(scope, () -> store.remember("待遗忘的记忆内容"));
        // 检索词必须命中该条记录，故取其正文的一部分作为查询。
        String query = "待遗忘的记忆内容";

        boolean forgotten = resolver.withScopeResult(scope, () -> store.forget(recorded.id()));
        assertThat(forgotten).isTrue();

        List<MemoryRecord> live = resolver.withScopeResult(scope, () -> store.search(query, 5));
        assertThat(live).noneMatch(record -> record.id().equals(recorded.id()));

        List<MemoryRecord> archived = resolver.withScopeResult(scope, () -> store.archived(5));
        assertThat(archived).anyMatch(record -> record.id().equals(recorded.id()));
    }

    @Test
    void 重复遗忘同一条记录返回否() {
        MemoryRecord recorded = resolver.withScopeResult(scope, () -> store.remember("只遗忘一次"));

        assertThat(resolver.withScopeResult(scope, () -> store.forget(recorded.id()))).isTrue();
        // 第二次遗忘没有可改写的目标：记录已是归档态，返回否而不是再次改写。
        assertThat(resolver.withScopeResult(scope, () -> store.forget(recorded.id()))).isFalse();
    }

    @Test
    void 跨作用域遗忘无效() {
        MemoryRecord recorded = resolver.withScopeResult(scope, () -> store.remember("不可被他人遗忘"));

        boolean forgotten = resolver.withScopeResult(
            MemoryScope.of(scope.tenantId(), "other-owner"), () -> store.forget(recorded.id()));
        assertThat(forgotten).isFalse();

        // 原作用域的记录必须仍是活跃态，未被他人改写。
        assertThat(resolver.withScopeResult(scope, () -> store.find(recorded.id()))).isPresent();
    }

    @Test
    void 归并不丢失原始信息() {
        MemoryRecord first = resolver.withScopeResult(scope, () -> store.remember("第一段：设备编号A"));
        MemoryRecord second = resolver.withScopeResult(scope, () -> store.remember("第二段：设备编号B"));
        MemoryRecord third = resolver.withScopeResult(scope, () -> store.remember("第三段：设备编号C"));

        Optional<MemoryRecord> merged = resolver.withScopeResult(scope,
            () -> store.consolidate(List.of(first.id(), second.id(), third.id())));

        assertThat(merged).isPresent();
        MemoryRecord mergedRecord = merged.orElseThrow();
        assertThat(mergedRecord.content())
            .contains("第一段：设备编号A")
            .contains("第二段：设备编号B")
            .contains("第三段：设备编号C");
        assertThat(mergedRecord.scope()).isEqualTo(scope);
        assertThat(mergedRecord.archived()).isFalse();
        // 归并必须生成<b>新</b>记录，而不是复用其中某一条的标识：
        // 复用标识会覆盖原记录，原文随之丢失。
        assertThat(mergedRecord.id()).isNotIn(first.id(), second.id(), third.id());

        // 合并后的记录必须可被再次读取，证明它确实落库而非只在内存中拼装。
        Optional<MemoryRecord> found = resolver.withScopeResult(scope, () -> store.find(mergedRecord.id()));
        assertThat(found).isPresent();
        assertThat(found.get().content()).contains("第一段：设备编号A", "第三段：设备编号C");
    }

    @Test
    void 跨作用域检索为空() {
        resolver.withScopeResult(scope, () -> store.remember("秘密内容不得跨作用域可见"));

        List<MemoryRecord> found = resolver.withScopeResult(
            MemoryScope.of(scope.tenantId(), "other-owner"), () -> store.search("秘密内容", 5));

        assertThat(found).isEmpty();
    }

    @Test
    void 跨作用域按标识读取为空() {
        MemoryRecord recorded = resolver.withScopeResult(scope, () -> store.remember("秘密内容不得跨作用域可见"));

        Optional<MemoryRecord> found = resolver.withScopeResult(
            MemoryScope.of(scope.tenantId(), "other-owner"), () -> store.find(recorded.id()));

        assertThat(found).isEmpty();
    }

    @Test
    void 跨租户归档查询为空() {
        MemoryRecord recorded = resolver.withScopeResult(scope, () -> store.remember("归档内容"));
        resolver.withScopeResult(scope, () -> store.forget(recorded.id()));

        List<MemoryRecord> archived = resolver.withScopeResult(
            MemoryScope.of("other-tenant", scope.ownerKey()), () -> store.archived(5));

        assertThat(archived).isEmpty();
    }

    @Test
    void 无有效作用域时拒绝写入() {
        assertThatThrownBy(() -> store.remember("x"))
            .isInstanceOf(IllegalStateException.class)
            .hasMessage("no active memory scope");
    }

    @Test
    void 无有效作用域时拒绝检索() {
        assertThatThrownBy(() -> store.search("x", 5))
            .isInstanceOf(IllegalStateException.class)
            .hasMessage("no active memory scope");
    }

    @Test
    void 遗忘不存在的记录返回否() {
        boolean forgotten = resolver.withScopeResult(scope, () -> store.forget("not-a-real-id"));

        assertThat(forgotten).isFalse();
    }

    /**
     * 返回确定性的本地嵌入模型：把文本的字符哈希累加到一个固定维度的向量。
     *
     * <p>本测试关注的是作用域过滤与软删除等<b>服务端语义</b>，
     * 不依赖语义相似度，因此词面级别的桩嵌入足够。
     *
     * @return 桩嵌入服务
     */
    private static EmbeddingService stubEmbeddings() {
        return new EmbeddingService() {
            @Override
            public List<double[]> embed(List<String> texts) {
                List<double[]> vectors = new ArrayList<>(texts.size());
                for (String text : texts) {
                    vectors.add(vectorOf(text));
                }
                return vectors;
            }

            /**
             * 把文本的字符哈希累加为向量。
             *
             * @param text 文本
             * @return 单位长度向量
             */
            private double[] vectorOf(String text) {
                double[] vector = new double[STUB_EMBEDDING_DIMENSIONS];
                for (int i = 0; i < text.length(); i++) {
                    int bucket = Math.floorMod(text.charAt(i) * 31 + i, STUB_EMBEDDING_DIMENSIONS);
                    vector[bucket] += 1.0;
                }
                return EmbeddingNormalizer.normalize(vector);
            }
        };
    }
}

