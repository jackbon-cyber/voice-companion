package com.company.bj.voice.cloud.memory;

import com.company.bj.voice.cloud.chroma.ChromaClient;
import com.company.bj.voice.cloud.chroma.ChromaCollectionName;
import com.company.bj.voice.cloud.chroma.ChromaGetResult;
import com.company.bj.voice.cloud.chroma.ChromaQueryResult;
import com.company.bj.voice.cloud.chroma.ChromaQueryResultReader;
import com.company.bj.voice.cloud.config.ChromaProperties;
import com.company.bj.voice.cloud.embed.EmbeddingService;
import com.company.bj.voice.cloud.memory.companion.MemoryChunkSplitter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

/**
 * 基于 Chroma 的长期记忆存储实现。
 *
 * <p>把每条长期记忆写成 Chroma 集合中的一条记录，用<b>元数据</b>承载作用域与归档标记：
 * <ul>
 *   <li>{@code scope_tenant} / {@code scope_owner} —— 作用域；</li>
 *   <li>{@code archived} —— 归档（软删除）标记；</li>
 *   <li>{@code weight} / {@code created_at} —— 权重与创建时间。</li>
 * </ul>
 *
 * <p><b>作用域隔离靠服务端的 {@code where} 过滤实现</b>，而不是在应用层
 * 取出结果后再筛。这样做有两个实质好处：
 * <ul>
 *   <li>过滤发生在服务端，返回给应用的就已经是「本作用域的记录」，
 *       应用层不可能因为漏写过滤条件而泄漏数据；</li>
 *   <li>{@code topK} 限制的是<b>过滤后</b>的命中数，因此跨作用域的记录
 *       不会「占位」掉本作用域记录的检索名额。</li>
 * </ul>
 *
 * <p><b>归档标记必须参与过滤</b>：只按作用域过滤而不区分归档状态，
 * 会被遗忘的记录仍会出现在检索结果里 —— 软删除就失去了意义。
 */
public class ChromaLongTermStore implements LongTermStore, ScoredMemorySearch {

    /** 元数据键：租户标识。 */
    static final String METADATA_SCOPE_TENANT = "scope_tenant";

    /** 元数据键：主体标识。 */
    static final String METADATA_SCOPE_OWNER = "scope_owner";

    /** 元数据键：归档标记。 */
    static final String METADATA_ARCHIVED = "archived";

    /** 元数据键：权重。 */
    static final String METADATA_WEIGHT = "weight";

    /** 元数据键：创建时间戳。 */
    static final String METADATA_CREATED_AT = "created_at";

    /**
     * 元数据键：父记录标识。
     *
     * <p>分片嵌入后，一条记忆对应多条片段记录，
     * 它们通过这个键绑定回同一条记忆。
     *
     * <p><b>为什么需要它</b>：协议层的 {@code citations} 语义是"记忆"，
     * 不是"片段"。命中片段后必须能找回它的父记忆，
     * 否则引用来源会指向一个用户从未说过的片段。
     *
     * <p>整句存储（未分片）的记录**没有**这个键 —— 老数据与新数据因此可共存。
     */
    static final String METADATA_PARENT_ID = "parent_id";

    /** 元数据键：父记录正文。分片记录冗余存一份原文，便于直接组装回复。 */
    static final String METADATA_PARENT_CONTENT = "parent_content";

    /** Chroma 元数据过滤操作符：等于。 */
    private static final String OPERATOR_EQUALS = "$eq";

    /** Chroma 元数据过滤组合操作符：逻辑与。 */
    private static final String OPERATOR_AND = "$and";

    /** 检索时需要回传的字段：正文、元数据与距离。 */
    private static final List<String> INCLUDE_FIELDS = List.of("documents", "metadatas", "distances");

    /** 列举时需要回传的字段：正文与元数据。 */
    private static final List<String> INCLUDE_GET_FIELDS = List.of("documents", "metadatas");

    /** 归并多条记录时正文之间的分隔符。 */
    private static final String CONSOLIDATION_SEPARATOR = "\n";

    /** 写入记录时的默认权重。 */
    private static final double DEFAULT_WEIGHT = 1.0;

    private final ChromaClient chroma;
    private final EmbeddingService embeddings;
    private final ChromaProperties props;
    private final ScopeResolver resolver;
    private final MemoryChunkSplitter chunkSplitter;

    /**
     * 构造长期记忆存储。
     *
     * @param chroma     Chroma 客户端
     * @param embeddings 嵌入服务，用于把文本转换为向量
     * @param props      Chroma 配置，提供长期记忆集合名
     * @param resolver   作用域解析器
     */
    public ChromaLongTermStore(ChromaClient chroma, EmbeddingService embeddings,
        ChromaProperties props, ScopeResolver resolver) {
        this(chroma, embeddings, props, resolver, new MemoryChunkSplitter());
    }

    /**
     * 构造长期记忆存储。
     *
     * @param chroma        Chroma 客户端
     * @param embeddings    嵌入服务，用于把文本转换为向量
     * @param props         Chroma 配置，提供长期记忆集合名
     * @param resolver      作用域解析器
     * @param chunkSplitter 记忆分片器
     */
    public ChromaLongTermStore(ChromaClient chroma, EmbeddingService embeddings,
        ChromaProperties props, ScopeResolver resolver, MemoryChunkSplitter chunkSplitter) {
        this.chroma = chroma;
        this.embeddings = embeddings;
        this.props = props;
        this.resolver = resolver;
        this.chunkSplitter = chunkSplitter;
    }

    @Override
    public MemoryRecord remember(String content) {
        return remember(content, DEFAULT_WEIGHT);
    }

    @Override
    public MemoryRecord remember(String content, double weight) {
        MemoryScope scope = resolver.current();
        String id = UUID.randomUUID().toString();
        long createdAt = System.currentTimeMillis();

        // 分片写入：一条记忆拆成若干检索片段，各自嵌入、各自入库，
        // 通过 parent_id 绑定回同一条记忆。
        //
        // **为什么这么做（实测依据）**：整句嵌入时，长记忆与短问句的向量相距较远，
        // 得分落到相关性下限以下 —— 机器人对刚刚听用户说过的事回答"没有记录"。
        // 分片后问句只需与其中最相关的一个片段相近。
        List<String> chunks = chunkSplitter.split(content);
        if (chunks.size() <= 1) {
            // 单片段（短记忆或切不动）走整句存储，不额外绑父记录 ——
            // 与历史数据保持同构，召回时无需特殊处理。
            chroma.upsert(resolveCollectionId(),
                List.of(id),
                List.of(embeddings.embed(content)),
                List.of(content),
                List.of(buildMetadata(scope, weight, createdAt)));
            return new MemoryRecord(id, content, weight, createdAt, scope, false);
        }

        List<String> chunkIds = new ArrayList<>(chunks.size());
        List<double[]> chunkEmbeddings = new ArrayList<>(chunks.size());
        List<String> chunkDocuments = new ArrayList<>(chunks.size());
        List<Map<String, Object>> chunkMetadatas = new ArrayList<>(chunks.size());

        for (String chunk : chunks) {
            chunkIds.add(UUID.randomUUID().toString());
            chunkEmbeddings.add(embeddings.embed(chunk));
            chunkDocuments.add(chunk);
            Map<String, Object> metadata = buildMetadata(scope, weight, createdAt);
            metadata.put(METADATA_PARENT_ID, id);
            metadata.put(METADATA_PARENT_CONTENT, content);
            chunkMetadatas.add(metadata);
        }

        chroma.upsert(resolveCollectionId(),
            chunkIds,
            chunkEmbeddings,
            chunkDocuments,
            chunkMetadatas);

        // 返回**父记录**而非某个片段：上层（引用来源、归档、归并）操作的单位是记忆。
        return new MemoryRecord(id, content, weight, createdAt, scope, false);
    }

    @Override
    public Optional<MemoryRecord> find(String id) {
        MemoryScope scope = resolver.current();
        String collectionId = resolveCollectionId();

        // 分片写入后，父记忆 id **本身不在库里**（库里只有片段 id），
        // 因此必须先按 parent_id 找片段。
        List<String> fragmentIds = findFragmentIds(collectionId, scope, id);
        if (!fragmentIds.isEmpty()) {
            ChromaGetResult fragmentResult = chroma.get(collectionId, fragmentIds);
            if (!fragmentResult.ids().isEmpty()) {
                MemoryRecord record = toRecord(fragmentResult, 0);
                if (scope.equals(record.scope()) && !record.archived()) {
                    return Optional.of(record);
                }
            }
            // 片段存在但已归档 —— 与整句路径的语义保持一致：归档记录不算"存在"。
            return Optional.empty();
        }

        ChromaGetResult result = chroma.get(collectionId, List.of(id));
        if (result.ids().isEmpty()) {
            return Optional.empty();
        }
        MemoryRecord record = toRecord(result, 0);
        // 作用域与归档状态任一不匹配都视为「不可见」：
        // 前者防止越权读取，后者保证软删除的记录不再被单独取到。
        if (!scope.equals(record.scope()) || record.archived()) {
            return Optional.empty();
        }
        return Optional.of(record);
    }

    @Override
    public List<MemoryRecord> search(String query, int topK) {
        MemoryScope scope = resolver.current();
        Map<String, Object> where = buildScopeWhere(scope, false);

        ChromaQueryResult result = chroma.query(resolveCollectionId(),
            embeddings.embed(query), topK, where, INCLUDE_FIELDS);
        return toParentRecords(result, scope);
    }

    /**
     * 把检索命中还原成<b>父记忆</b>并按父记忆去重。
     *
     * <p><b>为什么必须还原</b>：分片写入后，一条记忆对应多条片段记录。
     * 若直接把片段当作记忆返回：
     * <ul>
     *   <li>引用来源会指向一个<b>用户从未说过的片段</b>
     *       （用户说的是"我妈妈叫李芳，她很爱我…"，引用却指向"还总提醒我早点休息"）；</li>
     *   <li>同一条记忆的多个片段会占满召回窗口，把其他记忆挤出去；</li>
     *   <li>回复正文会变成片段的拼接，而不是一条完整记忆。</li>
     * </ul>
     *
     * <p><b>去重规则</b>：同一个父记忆的多个片段，只保留<b>得分最高</b>的那一个。
     * 保留最高分而不是求和 —— 片段得分不可比（"我妈妈叫李芳" 与
     * "还总提醒我早点休息" 语义强度本就不同），求和会系统性偏向片段多的记忆。
     *
     * <p><b>未分片的旧记录</b>没有 {@code parent_id} 元数据，
     * 直接以自身为父记忆返回 —— 新旧数据因此可以在同一个池子里竞争，无需迁移。
     *
     * @param result 检索结果
     * @param scope  当前作用域
     * @return 按父记忆去重后的记录列表
     */
    private List<MemoryRecord> toParentRecords(ChromaQueryResult result, MemoryScope scope) {
        Map<String, MemoryRecord> bestByParent = new LinkedHashMap<>();
        int hitCount = ChromaQueryResultReader.hitCount(result);

        for (int index = 0; index < hitCount; index++) {
            Map<String, Object> metadata = ChromaQueryResultReader.metadataAt(result, index);
            String parentId = stringOf(metadata, METADATA_PARENT_ID);
            String parentContent = stringOf(metadata, METADATA_PARENT_CONTENT);

            String recordId = parentId == null || parentId.isBlank()
                ? ChromaQueryResultReader.idAt(result, index)
                : parentId;
            String content = parentContent == null || parentContent.isBlank()
                ? ChromaQueryResultReader.documentAt(result, index)
                : parentContent;

            MemoryRecord record = new MemoryRecord(
                recordId,
                content,
                weightOf(metadata),
                createdAtOf(metadata),
                scope,
                archivedOf(metadata));

            // 同一父记忆只保留先出现的那条 —— 检索结果已按得分降序，
            // 因此"先出现"的就是得分最高的那一片。
            bestByParent.putIfAbsent(recordId, record);
        }
        return new ArrayList<>(bestByParent.values());
    }

    /**
     * 把检索命中还原成父记忆，并保留每个父记忆的<b>最高得分</b>。
     *
     * <p>与 {@link #toParentRecords} 的差别：这里保留了得分，
     * 因为相关性准入策略要靠得分判断能不能作为事实陈述。
     *
     * @param result 检索结果
     * @param scope  当前作用域
     * @return 按父记忆去重后的带得分记录
     */
    private List<ScoredMemoryRecord> toParentScored(ChromaQueryResult result, MemoryScope scope) {
        Map<String, ScoredMemoryRecord> bestByParent = new LinkedHashMap<>();
        int hitCount = ChromaQueryResultReader.hitCount(result);

        for (int index = 0; index < hitCount; index++) {
            Map<String, Object> metadata = ChromaQueryResultReader.metadataAt(result, index);
            String parentId = stringOf(metadata, METADATA_PARENT_ID);
            String parentContent = stringOf(metadata, METADATA_PARENT_CONTENT);

            String recordId = parentId == null || parentId.isBlank()
                ? ChromaQueryResultReader.idAt(result, index)
                : parentId;
            String content = parentContent == null || parentContent.isBlank()
                ? ChromaQueryResultReader.documentAt(result, index)
                : parentContent;

            double score = ChromaQueryResultReader.toScore(
                ChromaQueryResultReader.distanceAt(result, index));
            ScoredMemoryRecord scored = new ScoredMemoryRecord(
                new MemoryRecord(
                    recordId,
                    content,
                    weightOf(metadata),
                    createdAtOf(metadata),
                    scope,
                    archivedOf(metadata)),
                score);

            // 结果已按得分降序，先到先得即为最高分。
            bestByParent.putIfAbsent(recordId, scored);
        }
        return new ArrayList<>(bestByParent.values());
    }

    /**
     * 从元数据中取字符串值。
     *
     * @param metadata 元数据
     * @param key      键
     * @return 字符串值；不存在或类型不符时返回 {@code null}
     */
    private String stringOf(Map<String, Object> metadata, String key) {
        Object value = metadata == null ? null : metadata.get(key);
        return value instanceof String text ? text : null;
    }

    /**
     * 按语义检索当前作用域下的记忆，并带上检索得分。
     *
     * <p>与 {@link #search} 的唯一差别是<b>多带一个得分</b>。
     * 得分的价值在于区分"排在第一但其实不相关"与"排在第三但正是答案" ——
     * 调用方据此决定「可以当事实陈述」还是「宁可说没有记录」。
     *
     * <p>得分换算复用 {@code ChromaQueryResultReader#toScore}，
     * 与知识库检索、AgentScope 适配器用的是同一个公式 ——
     * 同一个数据在不同入口算出不同量纲的数，是极难定位的一类问题。
     *
     * @param query 查询文本
     * @param topK  返回条数上限
     * @return 带得分的命中记录，按得分降序排列
     * @throws IllegalStateException 当前没有活动作用域时抛出
     */
    @Override
    public List<ScoredMemoryRecord> searchScored(String query, int topK) {
        MemoryScope scope = resolver.current();
        Map<String, Object> where = buildScopeWhere(scope, false);

        ChromaQueryResult result = chroma.query(resolveCollectionId(),
            embeddings.embed(query), topK, where, INCLUDE_FIELDS);

        return toParentScored(result, scope);
    }

    @Override
    public List<MemoryRecord> list(int topK) {
        MemoryScope scope = resolver.current();
        Map<String, Object> where = buildScopeWhere(scope, false);

        // 列举不需要语义排序，直接按元数据过滤后取回，
        // 因此不经过 /query —— 那条路径必须提供查询向量，
        // 会为一次「把记录都列出来」的请求白白付出一次嵌入调用。
        ChromaGetResult result = chroma.getByWhere(resolveCollectionId(), where, topK, null,
            INCLUDE_GET_FIELDS);
        List<MemoryRecord> records = new ArrayList<>(result.ids().size());
        for (int i = 0; i < result.ids().size(); i++) {
            records.add(toRecord(result, i));
        }
        // 按创建时间倒序：控制台里最新的记忆排在最前面，与用户的时间直觉一致。
        records.sort((left, right) -> Long.compare(right.createdAt(), left.createdAt()));
        return dedupeByParent(records);
    }

    /**
     * 按父记忆去重，并保留每个父记忆的<b>最早写入</b>的那条。
     *
     * <p>分片写入后，一条记忆对应多条片段记录。
     * 列举时若不去重，用户会在控制台看到同一条记忆的多个片段。
     *
     * @param records 记录列表
     * @return 去重后的记录列表
     */
    private List<MemoryRecord> dedupeByParent(List<MemoryRecord> records) {
        Map<String, MemoryRecord> byParent = new LinkedHashMap<>();
        for (MemoryRecord record : records) {
            byParent.putIfAbsent(record.id(), record);
        }
        return new ArrayList<>(byParent.values());
    }

    @Override
    public boolean forget(String id) {
        MemoryScope scope = resolver.current();
        String collectionId = resolveCollectionId();

        // 分片写入后，传入的可能是**父记忆 id**，而库里存的是**片段 id**。
        // 先按父 id 找片段，片段不存在再按自身 id 找（未分片的旧记录）。
        List<String> fragmentIds = findFragmentIds(collectionId, scope, id);
        if (fragmentIds.isEmpty()) {
            ChromaGetResult fetched = chroma.get(collectionId, List.of(id));
            if (fetched.ids().isEmpty()) {
                return false;
            }
            MemoryRecord record = toRecord(fetched, 0);
            // 只有「本作用域下且未归档」的记录才允许遗忘：
            // 否则 forget 会把别的作用域的记录改写掉，或对已归档的记录重复改写。
            if (!scope.equals(record.scope()) || record.archived()) {
                return false;
            }
            // 软删除：只改写归档标记，绝不物理删除 —— 记录需保持可追溯、可恢复。
            chroma.update(collectionId, id, Map.of(METADATA_ARCHIVED, Boolean.TRUE));
            return true;
        }

        // 归档**全部片段**：只归档其中一个会让其余片段继续被召回，
        // 用户会看到"已删除的记忆"又冒出来。
        for (String fragmentId : fragmentIds) {
            chroma.update(collectionId, fragmentId, Map.of(METADATA_ARCHIVED, Boolean.TRUE));
        }
        return true;
    }

    /**
     * 找出属于指定父记忆的<b>全部片段 id</b>。
     *
     * @param collectionId 集合 id
     * @param scope        当前作用域
     * @param parentId     父记忆 id
     * @return 片段 id 列表；没有片段时返回空列表
     */
    private List<String> findFragmentIds(
        String collectionId, MemoryScope scope, String parentId) {
        Map<String, Object> where = new LinkedHashMap<>(1);
        List<Map<String, Object>> conditions = new ArrayList<>(4);
        conditions.add(equality(METADATA_SCOPE_TENANT, scope.tenantId()));
        conditions.add(equality(METADATA_SCOPE_OWNER, scope.ownerKey()));
        conditions.add(equality(METADATA_PARENT_ID, parentId));
        conditions.add(equality(METADATA_ARCHIVED, Boolean.FALSE));
        where.put(OPERATOR_AND, conditions);

        ChromaGetResult result = chroma.getByWhere(collectionId, where, 100, null,
            INCLUDE_GET_FIELDS);
        return result.ids();
    }

    @Override
    public List<MemoryRecord> archived(int topK) {
        MemoryScope scope = resolver.current();
        Map<String, Object> where = buildScopeWhere(scope, true);

        // 按元数据过滤而非语义检索。
        //
        // **为什么不用语义检索**：分片写入后，一条记忆对应多条片段，
        // 用固定查询词（"archived"）做语义检索命中的是"哪个片段最像 archived"，
        // 与"哪些记录被归档了"完全无关 —— 归档列表会随机漏掉记录。
        // 元数据过滤问的是确定性的事实。
        ChromaGetResult result = chroma.getByWhere(resolveCollectionId(), where, topK, null,
            INCLUDE_GET_FIELDS);
        List<MemoryRecord> records = new ArrayList<>(result.ids().size());
        for (int i = 0; i < result.ids().size(); i++) {
            records.add(toRecord(result, i));
        }
        // 去重：一条记忆的多个归档片段只显示一次。
        return dedupeByParent(records);
    }

    @Override
    public int clearCurrentScope() {
        MemoryScope scope = resolver.current();
        // 按作用域物理删除：连已归档记录一并清掉，让状态真正回到初始。
        // 删除条件里绝不能带 archived —— 否则归档记录会残留，
        // 记录总数持续增长，"已清空"就成了假象。
        return chroma.deleteByWhere(resolveCollectionId(), buildScopeOnlyWhere(scope));
    }

    @Override
    public Optional<MemoryRecord> consolidate(List<String> ids) {
        MemoryScope scope = resolver.current();
        if (ids == null || ids.isEmpty()) {
            return Optional.empty();
        }

        ChromaGetResult fetched = chroma.get(resolveCollectionId(), ids);
        List<String> contents = new ArrayList<>(fetched.ids().size());
        for (int i = 0; i < fetched.ids().size(); i++) {
            MemoryRecord record = toRecord(fetched, i);
            // 只归并当前作用域下、未归档的记录，避免把别人的记忆或已遗忘的记忆并进来。
            if (scope.equals(record.scope()) && !record.archived()) {
                contents.add(record.content());
            }
        }
        if (contents.isEmpty()) {
            return Optional.empty();
        }

        // 归并必须保留全部原文：拼接而非摘要，摘要在这里等于丢数据。
        String merged = String.join(CONSOLIDATION_SEPARATOR, contents);
        return Optional.of(remember(merged));
    }

    /**
     * 构造记录的元数据。
     *
     * @param scope     归属作用域
     * @param weight    权重
     * @param createdAt 创建时间戳
     * @return 元数据
     */
    private Map<String, Object> buildMetadata(MemoryScope scope, double weight, long createdAt) {
        Map<String, Object> metadata = new LinkedHashMap<>(5);
        metadata.put(METADATA_SCOPE_TENANT, scope.tenantId());
        metadata.put(METADATA_SCOPE_OWNER, scope.ownerKey());
        metadata.put(METADATA_WEIGHT, weight);
        metadata.put(METADATA_ARCHIVED, Boolean.FALSE);
        metadata.put(METADATA_CREATED_AT, createdAt);
        return metadata;
    }

    /**
     * 构造作用域过滤条件。
     *
     * @param scope         作用域
     * @param archivedState 是否只取已归档记录
     * @return where 表达式
     */
    private Map<String, Object> buildScopeWhere(MemoryScope scope, boolean archivedState) {
        List<Map<String, Object>> conditions = new ArrayList<>(3);
        conditions.add(equality(METADATA_SCOPE_TENANT, scope.tenantId()));
        conditions.add(equality(METADATA_SCOPE_OWNER, scope.ownerKey()));
        conditions.add(equality(METADATA_ARCHIVED, archivedState));
        Map<String, Object> where = new LinkedHashMap<>(1);
        where.put(OPERATOR_AND, conditions);
        return where;
    }

    /**
     * 构造<b>只按作用域</b>过滤的条件，不区分归档状态。
     *
     * <p>与 {@link #buildScopeWhere} 的差别在于少了 {@code archived} 条件 ——
     * "清空本作用域"意味着连已归档的记录一并清掉。
     *
     * @param scope 作用域
     * @return where 表达式
     */
    private Map<String, Object> buildScopeOnlyWhere(MemoryScope scope) {
        List<Map<String, Object>> conditions = new ArrayList<>(2);
        conditions.add(equality(METADATA_SCOPE_TENANT, scope.tenantId()));
        conditions.add(equality(METADATA_SCOPE_OWNER, scope.ownerKey()));
        Map<String, Object> where = new LinkedHashMap<>(1);
        where.put(OPERATOR_AND, conditions);
        return where;
    }

    /**
     * 构造单个等值条件。
     *
     * @param key   元数据键
     * @param value 期望值
     * @return 条件表达式
     */
    private Map<String, Object> equality(String key, Object value) {
        Map<String, Object> condition = new LinkedHashMap<>(1);
        condition.put(OPERATOR_EQUALS, value);
        Map<String, Object> expression = new LinkedHashMap<>(1);
        expression.put(key, condition);
        return expression;
    }

    /**
     * 把 Chroma 的检索结果转换成记忆记录列表。
     *
     * @param result Chroma 检索结果
     * @param scope  当前作用域，用于回填记录的归属
     * @return 记忆记录列表
     */
    private List<MemoryRecord> toRecords(ChromaQueryResult result, MemoryScope scope) {
        List<MemoryRecord> records = new ArrayList<>();
        int hitCount = ChromaQueryResultReader.hitCount(result);
        for (int i = 0; i < hitCount; i++) {
            Map<String, Object> metadata = ChromaQueryResultReader.metadataAt(result, i);
            records.add(new MemoryRecord(
                ChromaQueryResultReader.idAt(result, i),
                ChromaQueryResultReader.documentAt(result, i),
                weightOf(metadata),
                createdAtOf(metadata),
                scope,
                archivedOf(metadata)));
        }
        return records;
    }

    /**
     * 把 Chroma 的读取结果转换成一条记忆记录。
     *
     * @param result Chroma 读取结果
     * @param index  下标
     * @return 记忆记录
     */
    private MemoryRecord toRecord(ChromaGetResult result, int index) {
        Map<String, Object> metadata = index < result.metadatas().size()
            ? result.metadatas().get(index) : Map.of();
        String content = index < result.documents().size() ? result.documents().get(index) : "";
        // 分片记录要还原成父记忆：id 用父 id，正文用父正文。
        // 否则上层拿到的会是用户从未说过的片段。
        String parentId = stringOf(metadata, METADATA_PARENT_ID);
        String parentContent = stringOf(metadata, METADATA_PARENT_CONTENT);
        String recordId = parentId == null || parentId.isBlank()
            ? result.ids().get(index)
            : parentId;
        String recordContent = parentContent == null || parentContent.isBlank()
            ? content
            : parentContent;
        return new MemoryRecord(
            recordId,
            recordContent == null ? "" : recordContent,
            weightOf(metadata),
            createdAtOf(metadata),
            scopeOf(metadata),
            archivedOf(metadata));
    }

    /**
     * 从元数据读取权重。
     *
     * @param metadata 元数据
     * @return 权重，缺失时为默认权重
     */
    private double weightOf(Map<String, Object> metadata) {
        Object weight = metadata.get(METADATA_WEIGHT);
        return weight instanceof Number number ? number.doubleValue() : DEFAULT_WEIGHT;
    }

    /**
     * 从元数据读取创建时间戳。
     *
     * @param metadata 元数据
     * @return 时间戳，缺失时为 0
     */
    private long createdAtOf(Map<String, Object> metadata) {
        Object createdAt = metadata.get(METADATA_CREATED_AT);
        return createdAt instanceof Number number ? number.longValue() : 0L;
    }

    /**
     * 从元数据读取归档标记。
     *
     * @param metadata 元数据
     * @return 是否已归档
     */
    private boolean archivedOf(Map<String, Object> metadata) {
        return Boolean.TRUE.equals(metadata.get(METADATA_ARCHIVED));
    }

    /**
     * 从元数据读取作用域。
     *
     * @param metadata 元数据
     * @return 作用域，缺失时取缺省作用域
     */
    private MemoryScope scopeOf(Map<String, Object> metadata) {
        Object tenant = metadata.get(METADATA_SCOPE_TENANT);
        Object owner = metadata.get(METADATA_SCOPE_OWNER);
        return MemoryScope.of(
            tenant instanceof String value ? value : null,
            owner instanceof String value ? value : null);
    }

    /**
     * 解析出长期记忆集合 id。
     *
     * <p>配置里给的是集合<b>名</b>，而 Chroma 的接口需要集合 <b>id</b>，两者不能混用；
     * 此处先校验集合名（非法名在发起任何请求之前即被拒绝），
     * 再通过创建接口拿到 id（该接口是幂等的，同名集合复用同一 id）。
     *
     * @return 集合 id
     * @throws IllegalArgumentException 集合名非法时抛出
     */
    private String resolveCollectionId() {
        String collectionName = ChromaCollectionName.validate(props.getMemoryCollection());
        return chroma.createCollection(collectionName);
    }
}
