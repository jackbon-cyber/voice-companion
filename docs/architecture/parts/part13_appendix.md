# 附录 A：端侧关键接口定义

## A.1 会话状态机接口

```c
/* 会话状态定义：与端侧 session_manager 实现一一对应 */
typedef enum {
    SESSION_STATE_IDLE = 0,
    SESSION_STATE_LISTENING,
    SESSION_STATE_THINKING,
    SESSION_STATE_WAITING_CLOUD,
    SESSION_STATE_SPEAKING,
    SESSION_STATE_INTERRUPT
} session_state_t;

/* 端侧上云请求类型：按需扩展，云端按 type 分发 */
typedef enum {
    REQ_TYPE_AUDIO_FRAME = 0,
    REQ_TYPE_ASR_RESULT,
    REQ_TYPE_INTENT_RESULT,
    REQ_TYPE_INTERRUPT,
    REQ_TYPE_BARGE_IN,
    REQ_TYPE_TELEMETRY
} req_type_t;
```

## A.2 意图结果结构（端侧 → 云端）

```c
typedef struct {
    char        intent[32];      /* 受控意图标识，如 "device.volume_up" */
    float       confidence;      /* 0.0 - 1.0 */
    char        slots[256];      /* JSON 序列化槽位 */
    char        emotion[16];     /* 情感初判标签 */
    uint8_t     source;          /* 0=规则 1=端侧模型 2=云端 */
    uint32_t    asr_confidence;  /* ASR 置信度 × 100 */
} intent_result_t;
```

## A.3 降级判定

```c
/* 降级档位：网络/服务状态共同决定 */
typedef enum {
    DEGRADE_L0_NORMAL = 0,   /* 端侧 ASR + 云端 LLM + 云端 TTS */
    DEGRADE_L1_WEAK_NET,     /* 端侧 ASR + 云端轻量意图 + 云端 TTS */
    DEGRADE_L2_OFFLINE,      /* 端侧模型本地应答 + 本地提示音 */
    DEGRADE_L3_MINIMAL       /* 固定安抚话术 + 灯光情绪 */
} degrade_level_t;

/* 判定规则（端侧执行，避免依赖云端心跳）：
 * 1. 最近 5s 内上行失败 ≥ 2 次 → L1
 * 2. 连续 15s 无任何上行成功 → L2
 * 3. 端侧模型加载失败或推理异常 → L3
 * 4. 网络恢复后按 3 次成功握手逐级回升，不直接跳回 L0 */
```

## A.4 模型包解析

```c
/* manifest.json 关键字段（端侧解析后驻留只读区） */
typedef struct {
    char     package_version[16];
    char     platform[32];
    char     firmware_min[16];
    char     firmware_max[16];
    uint16_t model_count;
} pkg_manifest_t;

/* 单模型描述 */
typedef struct {
    char     id[32];        /* 如 "llm_lora_0_5b" */
    char     version[8];
    char     file[96];
    uint32_t size;
    uint8_t  sha256[32];
} pkg_model_t;
```

## 附录 B：端云接口契约

## B.1 WebSocket 通道

| 方向 | 消息类型 | 载荷 | 说明 |
|---|---|---|---|
| 上行 | `audio.frame` | PCM/Opus 分片 | 20ms/片，带 seq |
| 上行 | `asr.result` | text, confidence | 端侧 ASR 结果（可为空） |
| 上行 | `intent.result` | intent_result_t JSON | 端侧初判结果 |
| 上行 | `session.close` | reason | 结束会话 |
| 下行 | `agent.utterance` | text, emotion, audio | 流式语音片段 |
| 下行 | `agent.text` | text, emotion | 纯文本回复（用户关语音时） |
| 下行 | `session.end` | reason | 云端主动结束 |

**心跳**：客户端每 5s 发 `ping`，服务端 15s 无消息判定断链并回收会话。

## B.2 设备管理通道（MQTT）

| Topic | 方向 | 载荷 |
|---|---|---|
| `device/{deviceId}/up/report` | 上行 | 状态、版本、指标、故障码 |
| `device/{deviceId}/down/config` | 下行 | 运行参数（阈值、开关、超时） |
| `device/{deviceId}/down/profile` | 下行 | 画像增量 delta（≤4KB） |
| `device/{deviceId}/down/ota` | 下行 | OTA 通知（URL、sha256、签名、目标版本） |
| `device/{deviceId}/down/rollback` | 下行 | 回滚指令 |
| `device/{deviceId}/down/command` | 下行 | 远程诊断指令 |

## B.3 音频格式协商

| 参数 | 值 |
|---|---|
| 采样率 | 16000 Hz |
| 声道 | 单声道 |
| 位深 | 16 bit |
| 帧长 | 20 ms（320 样本） |
| 编码 | `pcm_s16le`（默认）/ `opus_16k_24kbps`（弱网） |

## 附录 C：云端服务内部接口

```java
/**
 * 记忆检索端口：与既有 openspec 变更中的 KnowledgeRetriever 保持一致的风格，
 * 作用域由存储实现内部强制附加，调用方不传 tenantId/userId。
 */
public interface MemoryRetriever {
    /**
     * 召回与当前用户相关的记忆。
     * @param query     检索式（已做画像加权改写）
     * @param topK      返回条数，长期/情景/短期三路各自取
     * @return 三路召回结果，交由融合排序器处理
     */
    MemoryRecall recall(String query, int topK);
}
```

```java
/**
 * 语音合成端口：屏蔽自建 Omni-TTS 与第三方 TTS 的差异，支持降级切换。
 */
public interface SpeechSynthesizer {
    /**
     * 以流式方式合成，调用方按片段消费以便尽早下发。
     * @param request 合成请求（文本、personaId、speakerId、emotion、语速）
     * @return 流式语音片段生产者
     */
    Flux<SpeechChunk> synthesize(SpeechRequest request);
}
```

## 附录 D：OTA 与部署脚本要点

```bash
# 1) 端侧构建（MCU 档）
cd firmware && make MCU=1 PLATFORM=stm32n6 MODEL_PKG=dist/companion_model_pkg.bin
# 产物：build/firmware.bin + build/partition_table.json

# 2) 打包模型并签名
python scripts/package_model.py --manifest build/manifest.json --out dist/companion_model_pkg.bin --sign-key $DEVICE_SIGN_KEY

# 3) 固件与模型一起发布到 OTA 服务
ota-cli publish --product companion --version 2.1.0 \
               --firmware build/firmware.bin --models dist/companion_model_pkg.bin --canary 5

# 4) 观察 15 分钟指标后再放量
ota-cli rollout --product companion --version 2.1.0 --stage 20
ota-cli rollout --product companion --version 2.1.0 --stage 100
```

**回滚**：`ota-cli rollback --product companion --to 2.0.4 --reason "意图准确率下降 3.2pt"`；端侧在收到回滚指令后从备用分区启动旧版本并上报 `rollback_success`。

## 附录 E：评测集与门禁规范

| 评测集 | 规模 | 内容 | 门禁指标 |
|---|---|---|---|
| 意图评测集 | 3000 条 | 受控意图 + 闲聊负样本 + 口音样本 | 准确率 ≥ 90%；负样本误触发 ≤ 3% |
| 记忆召回集 | 500 条 query | query → 相关记忆 id 集合 | Recall@6 ≥ 0.70；P95 ≤ 150ms |
| **记忆作答集** | **500 条 query + 100 条无答案问句** | **Top-1 作答内容 + 库里没有对应事实的干扰项** | **作答准确率 ≥ 0.95；作答率 ≥ 0.75；编造率 ≤ 0.05** |
| 端侧 ASR 集 | 20 小时真人语料 | 安静/噪声/远场/口音 | WER ≤ 12%（base 档） |
| 安全集 | 5000 条 | 违规诱导 + 正常陪伴 | 拦截召回 ≥ 99%；误伤 ≤ 0.3% |
| 共情集 | 400 条 | 情绪 × 场景矩阵 | 恰当率 ≥ 85%；禁忌违反 = 0 |
| 端侧模型准入 | 每模型一套 | 量化前后对比 | 见 4.8 节 Gate 表 |

**记忆作答集为什么必须包含"无答案问句"**（这一条是 §7.6.1 的直接推论）：
只测答得上的问题时，**永远拒答**的系统也能拿满分，门禁形同虚设。
加上无答案问句之后，"拒答"第一次有了可衡量的价值 ——
对答不上的问题拒答 = 正确，作答 = 编造。

**评测纪律**：评测集与训练集按 `session_id` 严格互斥；评测脚本入库并进 CI，指标不达标则构建失败（沿用仓库既有 `RetrievalQualityReport` 断言方式）。

**阈值推导纪律**（比"评测集与训练集互斥"更容易被违反）：
**相关性下限这类阈值必须在留出集上独立推导，不能在门禁要用的那批数据上挑**。
在评测集上挑出来的阈值是拿答案调答案，换批数据立刻失效 ——
它测的是"阈值对这批数据合不合身"，不是"系统能力够不够"。
留出集的要求是：**语料与评测集相同（同一批记忆事实），问句完全不重合**。
