package com.company.bj.voice.cloud.config;

import com.company.bj.voice.cloud.auth.HandshakeAuthInterceptor;
import com.company.bj.voice.cloud.auth.TokenAuthenticator;
import com.company.bj.voice.cloud.chroma.ChromaClient;
import com.company.bj.voice.cloud.downlink.DownlinkPublisher;
import com.company.bj.voice.cloud.embed.EmbeddingService;
import com.company.bj.voice.cloud.embed.LocalEmbeddingService;
import com.company.bj.voice.cloud.memory.ChromaLongTermStore;
import com.company.bj.voice.cloud.memory.LongTermStore;
import com.company.bj.voice.cloud.memory.MemoryScope;
import com.company.bj.voice.cloud.memory.ScopeResolver;
import com.company.bj.voice.cloud.memory.SessionOwnerRegistry;
import com.company.bj.voice.cloud.memory.companion.CompanionMemoryClassifier;
import com.company.bj.voice.cloud.memory.companion.FingerprintCalculator;
import com.company.bj.voice.cloud.memory.companion.MemoryRelevancePolicy;
import com.company.bj.voice.cloud.memory.companion.MemoryUpdateService;
import com.company.bj.voice.cloud.memory.companion.ScopedCompanionMemoryStore;
import com.company.bj.voice.cloud.memory.companion.SessionMemoryOrchestrator;
import com.company.bj.voice.cloud.protocol.ProtocolValidator;
import com.company.bj.voice.cloud.reply.MemoryGroundedReplyService;
import com.company.bj.voice.cloud.reply.OpenAiCompatibleReplyPhrasing;
import com.company.bj.voice.cloud.reply.ReplyPhrasing;
import com.company.bj.voice.cloud.reply.TemplateReplyPhrasing;
import com.company.bj.voice.cloud.session.ProcessingUnitDirectory;
import com.company.bj.voice.cloud.session.SessionRegistry;
import com.company.bj.voice.cloud.session.SessionReroutingService;
import java.net.http.HttpClient;
import java.nio.file.Path;
import java.time.Clock;
import java.util.List;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * 云端基础 Bean 配置。
 *
 * <p>这些 Bean 单独成配置类，是为了避开与 {@link WebSocketConfig} 的循环依赖：
 * WebSocket 配置需要上行处理器，上行处理器需要会话服务，会话服务又需要
 * 这里的协议校验器与会话注册表 —— 把 Bean 定义与 WebSocket 注册拆开，
 * 依赖链才是单向的。
 */
@Configuration
public class CloudBeansConfig {

    /** 协议 schema 所在目录。协议 schema 与 Python 侧共用同一批文件。 */
    private static final Path SCHEMA_DIR = Path.of("..", "protocol", "schema");

    /**
     * 构造协议校验器。
     *
     * @return 协议校验器
     */
    @Bean
    public ProtocolValidator protocolValidator() {
        return new ProtocolValidator(SCHEMA_DIR);
    }

    /**
     * 构造下行发布器。
     *
     * @param protocolValidator 协议校验器
     * @return 下行发布器
     */
    @Bean
    public DownlinkPublisher downlinkPublisher(ProtocolValidator protocolValidator) {
        return new DownlinkPublisher(protocolValidator);
    }

    /**
     * 构造会话注册表。
     *
     * <p>默认按会话标识的哈希取模分片。真实部署应换成一致性哈希 ——
     * 取模分片在处理单元数量变化时会重新映射几乎所有会话。
     *
     * @return 会话注册表
     */
    @Bean
    public SessionRegistry sessionRegistry() {
        return new SessionRegistry(sessionId -> "unit-" + Math.abs(sessionId.hashCode() % 3));
    }

    /**
     * 构造上行通道鉴权器。
     *
     * <p>凭据来自环境变量 {@code VOICE_UPLINK_TOKEN}，仓库内不出现真实值。
     * 未设置时**不启用鉴权** —— 这是开发期的默认形态，让"克隆下来就能跑"成立。
     * 生产部署必须设置，否则上行通道对任何人都开放。
     *
     * @param uplinkToken 期望的凭据；未设置时为空
     * @return 鉴权器
     */
    @Bean
    public TokenAuthenticator tokenAuthenticator(
            @Value("${voice.uplink.token:${VOICE_UPLINK_TOKEN:}}") String uplinkToken) {
        return new TokenAuthenticator(uplinkToken);
    }

    /**
     * 构造握手鉴权拦截器。
     *
     * @param tokenAuthenticator 鉴权器
     * @return 握手鉴权拦截器
     */
    @Bean
    public HandshakeAuthInterceptor handshakeAuthInterceptor(TokenAuthenticator tokenAuthenticator) {
        return new HandshakeAuthInterceptor(tokenAuthenticator);
    }

    /**
     * 构造处理单元可用性来源。
     *
     * <p>第一阶段进程内只有固定的三个逻辑分片，全部视为可用。
     * 真实部署应换成从注册中心或编排系统查询 —— 这正是
     * {@link ProcessingUnitDirectory} 存在的理由：替换实现即可，
     * 重路由逻辑不用改。
     *
     * @return 处理单元可用性来源
     */
    @Bean
    public ProcessingUnitDirectory processingUnitDirectory() {
        return () -> List.of("unit-0", "unit-1", "unit-2");
    }

    /**
     * 构造会话重路由服务。
     *
     * @param sessionRegistry 会话注册表
     * @param unitDirectory 处理单元可用性来源
     * @return 会话重路由服务
     */
    @Bean
    public SessionReroutingService sessionReroutingService(
            SessionRegistry sessionRegistry, ProcessingUnitDirectory unitDirectory) {
        return new SessionReroutingService(sessionRegistry, unitDirectory);
    }

    /**
     * 构造时钟。
     *
     * <p>注入而非直接取系统时间，便于测试里控制时间流逝。
     *
     * @return 时钟
     */
    @Bean
    public Clock clock() {
        return Clock.systemUTC();
    }

    /**
     * 构造作用域解析器。
     *
     * @return 作用域解析器
     */
    @Bean
    public ScopeResolver scopeResolver() {
        return new ScopeResolver();
    }

    /**
     * 构造会话归属注册表。
     *
     * @return 会话归属注册表
     */
    @Bean
    public SessionOwnerRegistry sessionOwnerRegistry() {
        return new SessionOwnerRegistry(MemoryScope.DEFAULT_TENANT_ID);
    }

    /**
     * 构造长期记忆存储。
     *
     * <p>依赖 Chroma 与本地嵌入服务。两者不可用时**不阻止应用启动** ——
     * 启动失败会让"克隆下来就能跑"不成立；记忆不可用时，
     * 上行链路仍能建立会话并下发回复，只是不带记忆引用。
     *
     * @param chromaProperties Chroma 配置
     * @param embeddingProperties 嵌入配置
     * @param scopeResolver 作用域解析器
     * @return 长期记忆存储
     */
    @Bean
    public LongTermStore longTermStore(
            ChromaProperties chromaProperties,
            EmbeddingProperties embeddingProperties,
            ScopeResolver scopeResolver) {
        ChromaClient chroma = new ChromaClient(
                chromaProperties,
                java.net.http.HttpClient.newHttpClient(),
                new com.fasterxml.jackson.databind.ObjectMapper());
        EmbeddingService embeddings = new LocalEmbeddingService(embeddingProperties);
        return new ChromaLongTermStore(chroma, embeddings, chromaProperties, scopeResolver);
    }

    /**
     * 构造陪伴域长期记忆存储。
     *
     * <p><b>隔离由这一层强制施加</b>：它包在底层存储之外，
     * 读出后再校验一次归属 —— 即使底层实现有疏漏，越权记录也到不了上层。
     *
     * @param longTermStore 底层长期记忆存储
     * @param scopeResolver 作用域解析器
     * @return 陪伴域长期记忆存储
     */
    @Bean
    public ScopedCompanionMemoryStore scopedCompanionMemoryStore(
            LongTermStore longTermStore,
            ScopeResolver scopeResolver) {
        return new ScopedCompanionMemoryStore(longTermStore, scopeResolver);
    }

    /**
     * 构造记忆分类器。
     *
     * @return 记忆分类器
     */
    @Bean
    public CompanionMemoryClassifier companionMemoryClassifier() {
        return new CompanionMemoryClassifier();
    }

    /**
     * 构造记忆更新服务。
     *
     * @param scopedCompanionMemoryStore 陪伴域长期记忆存储
     * @return 记忆更新服务
     */
    @Bean
    public MemoryUpdateService memoryUpdateService(
            ScopedCompanionMemoryStore scopedCompanionMemoryStore) {
        return new MemoryUpdateService(scopedCompanionMemoryStore, FingerprintCalculator.lexical());
    }

    /**
     * 构造会话记忆编排服务。
     *
     * @param scopedCompanionMemoryStore 陪伴域长期记忆存储
     * @param scopeResolver 作用域解析器
     * @param sessionOwnerRegistry 会话归属注册表
     * @param classifier 记忆分类器
     * @param updateService 记忆更新服务
     * @return 会话记忆编排服务
     */
    @Bean
    public SessionMemoryOrchestrator sessionMemoryOrchestrator(
            ScopedCompanionMemoryStore scopedCompanionMemoryStore,
            ScopeResolver scopeResolver,
            SessionOwnerRegistry sessionOwnerRegistry,
            CompanionMemoryClassifier classifier,
            MemoryUpdateService updateService) {
        return new SessionMemoryOrchestrator(
                scopedCompanionMemoryStore, scopeResolver, sessionOwnerRegistry,
                classifier, updateService);
    }

    /**
     * 构造措辞生成器。
     *
     * <p><b>为什么是"有凭据才启用"而不是"总是启用"</b>：
     * "克隆下来就能跑"是本作品面向求职场景的第一目标。
     * 没有凭据时用模板，行为完全确定、零延迟、零成本；
     * 配置了凭据时自动切到大模型，表达更自然。
     *
     * <p>大模型的失败在 {@link OpenAiCompatibleReplyPhrasing} 内部被兜住
     * （返回空串 → 调用方退回模板），因此这里不需要额外的降级开关 ——
     * 少一个开关就少一种"配错了但看不出来"的状态。
     *
     * @param llmProperties 大模型配置
     * @return 措辞生成器
     */
    @Bean
    public ReplyPhrasing replyPhrasing(LlmProperties llmProperties) {
        if (!llmProperties.enabled()) {
            return new TemplateReplyPhrasing();
        }
        return new OpenAiCompatibleReplyPhrasing(
                llmProperties,
                HttpClient.newHttpClient(),
                new com.fasterxml.jackson.databind.ObjectMapper());
    }

    /**
     * 构造记忆支撑的回复生成服务。
     *
     * @param orchestrator 记忆编排服务
     * @param phrasing     措辞生成器
     * @return 回复生成服务
     */
    @Bean
    public MemoryGroundedReplyService memoryGroundedReplyService(
            SessionMemoryOrchestrator orchestrator, ReplyPhrasing phrasing) {
        return new MemoryGroundedReplyService(
                orchestrator, MemoryRelevancePolicy.standard(), phrasing);
    }
}
