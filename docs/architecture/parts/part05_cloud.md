# 5. 云端总体架构与服务划分

## 5.1 服务清单

沿用仓库既有技术栈（Spring Boot 3.3.5、AgentScope 2.0.4、Nacos 3.2、Higress、PostgreSQL + pgvector、Chroma 1.5.9、Redis、RocketMQ），**不新建第二套框架**。

| 服务 | 职责 | 技术 | 扩缩容依据 |
|---|---|---|---|
| `gateway-voice` | 设备接入、鉴权、音频通道、会话路由 | Spring Boot + Netty(WebSocket) + MQTT | 连接数 |
| `asr-service` | 云端 ASR 兜底、热词定制、标点 | FunASR/Paraformer + Triton | 并发路数 |
| `intent-service` | 三级意图判定、澄清状态机、槽位管理 | AgentScope + 规则引擎 + MiniLM | QPS |
| `companion-agent` | 情感陪伴主 Agent、角色扮演、工具编排 | AgentScope 2.0.4 | 并发会话 |
| `memory-service` | 四层记忆读写、召回、衰减 | AgentScope SPI + Chroma + PG | QPS + 召回延迟 |
| `profile-service` | 用户画像与偏好抽取、千人千面 | 规则 + LLM 抽取 + PG | 批处理为主 |
| `tts-service` | TTS 合成、音色克隆、情感注入、流式分片 | Qwen2.5-Omni-TTS / 第三方 TTS | 并发路数 |
| `safety-service` | 内容审核、敏感识别、未成年人策略 | 规则 + 分类模型 | QPS |
| `device-service` | 设备注册、OTA、配置、遥测、影子灰度 | Spring Boot + Nacos | 设备数 |
| `cost-service` | Token/算力计量、成本核算、配额 | Spring Boot | 无状态 |

**复用既有资产**：仓库 `openspec/changes/add-agentscope-chroma-memory-kb` 已完成 Chroma REST 客户端（`ChromaClient`）、`ChromaStore implements VDBStoreBase`、`ChromaLongTermMemory`、`ScopeResolver`、检索质量门禁脚本。**本方案直接复用，不重建**；新增的是语音域的组装层与音频通道。

## 5.2 端云协议

| 方向 | 协议 | 载荷 |
|---|---|---|
| 音频上行 | WebSocket（二进制帧）或 MQTT | 16k PCM/Opus 分片，20ms/帧，带 seq 与时间戳 |
| 控制上行 | MQTT QoS1 | JSON：意图结果、置信度、设备状态、遥测 |
| 音频下行 | WebSocket | 流式 PCM 分片，带首包标记与情感事件字段 |
| 配置/OTA | HTTPS + MQTT 通知 | 版本清单、URL、签名、增量画像 delta |

**端云消息示例**：

```json
{
  "type": "audio.frame",
  "sessionId": "s_8f3a2c",
  "seq": 1423,
  "sampleRate": 16000,
  "encoding": "pcm_s16le",
  "payload": "<base64>",
  "timestampMs": 1731283745123
}
```

```json
{
  "type": "agent.utterance",
  "sessionId": "s_8f3a2c",
  "audio": "<base64 pcm>",
  "audioFormat": "pcm_s16le",
  "sampleRate": 16000,
  "emotion": "warm",
  "personaId": "xiaoban_v3",
  "isFinal": false,
  "text": "听起来今天不太顺利",
  "ttsFirstPacket": true
}
```

**会话粘滞**：同一 `sessionId` 的音频流与 Agent 实例必须落在同一 Pod（或通过 Redis 共享上下文），否则流式 TTS 与记忆读写会跨节点失配。实现上用 Redis 存会话上下文 + 一致性哈希环做粘滞路由。

> **为什么必须是一致性哈希环，而不是哈希取模**：取模在单元数量变化时会让
> **几乎所有会话重新映射** —— 扩容一次等于把所有在线设备踢下线重连。
> 一致性哈希环把影响面限制在少数会话上。
>
> **当前实现状态**：会话到单元的映射由**注入的函数**决定，
> 会话上下文存**进程内**（多实例部署时不共享）。
> 即：**本方案不能宣称云端可水平扩容** —— 该能力待 Redis 与一致性哈希环落地后成立。

## 5.3 意图三级判定

```
① 端侧规则命中（本地，≤ 20ms）
   高置信固定意图（音量/灯光/计时/闹钟）→ 直接本地执行，不上云
② 端侧小模型初判（≤ 120ms）
   命中受控意图 → 上云时携带 intent + confidence，云端跳过 LLM 分类
③ 云端 LLM 分类（≤ 150ms，仅未被前两级判定时）
   返回 {intent, confidence, missing_slots}
   confidence ≥ 0.90 → 直接进入编排
   confidence < 0.90 → 生成澄清问题，最多 3 轮
```

**三级判定的收益**（按典型会话构成估算）：约 40% 的轮次由规则/端侧模型直接判定，云端 LLM 分类调用量下降 40%，既省成本又降延迟。

## 5.4 多轮会话澄清

| 项 | 规格 |
|---|---|
| 澄清触发 | 意图置信度 < 0.90，或关键槽位缺失 |
| 澄清轮次上限 | 3 轮；超过走兜底路由并标记 `fallback=true` |
| 澄清句生成 | 模板优先（高频槽位），LLM 兜底 |
| 槽位合并 | 增量合并到会话 `slotStore`，不清空已有槽位 |
| 状态存储 | Redis（TTL 30 分钟）+ 会话内 AgentState |
| 例子 | "帮我订个餐" → 缺 `菜品/时间/地点` → "想吃什么？" → "火锅" → 合并后继续 |

**澄清的陪伴场景特化**：陪伴类对话里过度澄清会破坏情绪流。规则是——**情绪类意图不澄清，直接用"我在这儿"式承接 + 一个轻量追问**；只有涉及事实性任务（订餐、查日程）才走严格槽位澄清。

## 5.5 多智能体编排（AgentScope）

| Agent | 职责 | 触发 | 工具/资源 |
|---|---|---|---|
| `CompanionMainAgent` | 主控：情绪识别、话题延续、决定是否澄清、输出治理 | 全部轮次 | 记忆检索、画像查询、TTS、工具 |
| `RoleplayAgent` | 严格按人设卡扮演，不越界 | 检测到人设关键词或用户明确要求 | 人设卡检索 |
| `EmpathyAgent` | 情绪共情：识别情绪、生成共情回应与陪伴策略 | 情绪信号强（负面） | 情绪知识检索 |
| `MemoryAgent` | 记忆写入：抽取事实/偏好/事件并分类落库 | 每轮结束异步 | Chroma、PG |
| `ProfileAgent` | 画像更新：从会话更新偏好、话题权重 | 每 5 轮或会话结束 | PG、向量库 |
| `SafetyAgent` | 输入输出双向审核 | 全部轮次 | 审核规则、分类模型 |
| `ContentAgent` | 内容类（讲笑话、讲故事、念诗） | 内容类意图 | 内容库检索 |

**编排规则**：

1. 主 Agent 只做"路由与决策"，不直接执行业务逻辑（A3 约束：扩展点用接口+策略，不用 if-type 堆砌）。
2. 每个子 Agent 以独立 `AgentState` 运行，通过结构化消息交接，不共享可变上下文。
3. 子 Agent 结果由主 Agent 做**一致性裁决**：多 Agent 输出冲突时按优先级（安全 > 事实 > 人设 > 情绪）取舍。
4. 主 Agent 输出前必经 Safety Agent 输出端审核；审核不通过则回落到安全话术模板。

```java
// 子 Agent 分发：用策略表路由，避免在主流程里堆 if (intent == X)
@Component
public class AgentDispatchRegistry {
    /** 意图 → 子 Agent 处理器 的策略注册表；新增子 Agent 只需注册，不改主流程。 */
    private final Map<String, SubAgentHandler> handlers;

    public AgentDispatchRegistry(List<SubAgentHandler> handlerList) {
        this.handlers = handlerList.stream()
                .collect(Collectors.toMap(SubAgentHandler::supportedIntents, h -> h, (a, b) -> a));
    }

    public SubAgentHandler resolve(String intent) {
        return handlers.get(intent);
    }
}
```

## 5.6 会话上下文装配

装配顺序（固定，总预算 ≤ 1500 token）：

| 顺序 | 内容 | token 预算 |
|---|---|---|
| 1 | 系统提示（人设卡 + 安全边界 + 当前情绪策略） | 400 |
| 2 | 用户画像卡（称呼、语速、话题权重、忌讳） | 200 |
| 3 | 长期记忆 Top3 + 情景记忆 Top2（RRF 融合后） | 500 |
| 4 | 短期记忆最近 4 轮 | 300 |
| 5 | 当前轮输入 + 槽位状态 | 100 |

装配器实现为独立组件，与记忆服务解耦，可独立替换为"摘要式历史"策略。

> **P0-2 修订说明**：本节预算 1500 token 是 §9.3 成本模型的**唯一权威口径**。按此重算，单会话成本约 ¥0.159（原文写 ¥0.053，误差 3 倍）。优化路径为：① 预算压至 800 token；② 短期历史改**滚动摘要**（每 5 轮压成 100 token）；③ 系统提示与人设卡走 provider **prompt cache**（稳定前缀）；④ 引入**模型分层**（简单陪伴走小模型或缓存回复）。全部落地后约 ¥0.096/会话，**§1.1 的 ¥0.06 目标仍不可达，定价需按 ¥0.10–0.12 重算**。详见 §12.1 P0-2。

## 5.7 输出治理

| 治理项 | 规则 |
|---|---|
| 长度控制 | 按用户偏好（简短/详细）与情绪场景决定目标长度，默认 ≤ 60 字 |
| 重复抑制 | 与最近 3 轮回复做相似度检查，> 0.85 则重生成 |
| 事实边界 | 无检索支撑的事实性陈述走"不确定"话术，不编造 |
| 打断友好 | 输出为句子级片段，句间可被打断 |
| 幻觉防护 | 陪伴场景允许主观表达，但涉及日期、姓名、地点等具体事实必须来自记忆或检索结果 |
