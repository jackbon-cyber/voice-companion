# 二次开发指南

> 面向两类人：**接手公司落地**的工程师，以及**要复用这个骨架**的人。
>
> 每一类改动都标出：**改哪里 → 要跑什么验证 → 会牵动什么**。
> 最后一节是"改动前的自检清单"，照着走能避开绝大多数坑。

---

## 0. 三条铁律

先记住这三条，比记住任何 API 都重要。

### 铁律一：协议只改一处

端云协议的事实来源是 **`core/protocol/schema/*.schema.json`**，
Python 与 Java 两侧都读同一份文件。

**不要**在 Python 或 Java 侧另写一份校验逻辑。校验入口：

| 侧 | 入口 |
|---|---|
| Python | `core.protocol.validator.build_validator(name)` / `validation_errors(name, payload)` |
| Java | `com.company.bj.voice.cloud.protocol.ProtocolValidator` |

改协议后**必跑**：

```powershell
powershell -ExecutionPolicy Bypass -File core\scripts\validate-protocol.ps1
F:\tools\python313\python.exe -m pytest core\tests\protocol -v
& 'D:\apache-maven-3.9.2\apache-maven-3.9.2\bin\mvn.cmd' test -Dtest=ProtocolValidatorTest
```

三个命令全过才算协议改动完成。

### 铁律二：业务逻辑不进 `deploy/`

`deploy/` 是公司私有层，不在开源仓库、不走评审。
业务逻辑沉进去 = 绕过所有质量门禁。

判断标准：**这段代码换个公司还要不要改？**
要改 → 业务逻辑 → 进 `core/`；不改 → 基础设施适配 → 留 `deploy/`。

详见 `deploy/README.md`。

### 铁律三：先搜再建

新增任何类之前，先在项目里搜同类抽象：

```powershell
# 搜同名后缀
Get-ChildItem core -Recurse -Include *Service.java,*Repository.java,*Handler.java,*Strategy.java,*Converter.java | Select-Object Name
```

存在可复用抽象时**必须扩展或组合**，不要新建平行实现。
云端已有：`SessionRegistry`（会话注册）、`ProtocolValidator`（协议校验）、
`SessionLifecycleService`（会话生命周期）、`SessionWebSocketHandler`（上行入口）。

---

## 1. 换人设

### 1.1 人设卡定义在哪

**当前状态**：**未实现**（OpenSpec 任务 7.6）。
人设的**协议落点**已经确定 —— `text-reply` 与 `voice-chunk` 都有 `emotion` 字段，
人设对回复的影响通过该字段体现。

### 1.2 要改什么

| 步骤 | 改哪里 | 验证 |
|---|---|---|
| 定义人设卡结构 | `core/protocol/schema/` 新增 `persona-card.schema.json` | `validate-protocol.ps1` |
| 人设卡加载与热更 | 新增 `core/cloud/.../persona/` 包 | 新增单测 |
| 人设影响输出 | 云端意图编排（任务 7.4 的主控智能体） | 7.4 的测试 |
| 人设影响端侧话术 | `core/edge/dialog/phrases.py` 的情绪分桶 | `core/tests/edge/dialog/test_engine.py` |

### 1.3 牵动什么

人设卡结构会进协议，因此**两侧都要升级**。
端侧若也要区分人设，`intent-report` 需要能表达"当前人设下这个意图的含义" ——
这会触发协议变更，走铁律一。

---

## 2. 换模型

### 2.1 端侧 ASR

**当前状态**：`core/edge/asr/recognizer.py` 有三个实现：

| 实现 | 用途 |
|---|---|
| `FasterWhisperRecognizer` | 生产路径，真实模型 |
| `NullRecognizer` | 降级路径，模型缺失时用，识别结果恒空 |
| `ScriptedRecognizer` | **仅模拟端用**，按脚本返回文本 |

**换成别的 ASR（如厂商 SDK）**：实现 `SpeechRecognizer` 协议，
在 `create_recognizer` 风格的工厂里注册，**不要改** `IntentDetector` 或上行客户端。

```python
class VendorRecognizer:
    """厂商 SDK 识别适配。"""

    def transcribe(self, pcm: bytes) -> RecognitionResult:
        ...
        return RecognitionResult(text=text, confidence=confidence, language="zh")
```

**验证**：`core/tests/edge/asr/test_recognizer.py`；
**特别注意**：换模型后**必须重测端侧识别耗时** ——
识别耗时会改变整条链路的时延预算。测量入口见第 4 节。

### 2.2 端侧对话

**当前状态**：`core/edge/dialog/engine.py` 的 `LocalDialogEngine` 协议，
两个实现：`LlamaCppDialogEngine`（GGUF Q4_K_M）、`PhraseBankDialogEngine`（话术库）。

**换成别的本地模型**：实现 `LocalDialogEngine`，改 `create_dialog_engine`。
**保留回落**：任何错误都必须回落到话术库，不能让对话中断 ——
这是 `test_engine.py` 里明确断言的行为。

### 2.3 端侧意图小模型

**当前状态**：`core/edge/intent/detector.py` 的 `LocalIntentModel` 协议
（`classify(text) -> (intent, confidence)`）。

**换模型**：实现该协议，传给 `IntentDetector(rules=..., local_model=...)`。
**注意阈值**：`MODEL_CONFIDENCE_THRESHOLD = 0.6`，
低于该值视为模型没把握，交给云端。换模型后这个阈值**需要重新标定**。

### 2.4 云端大模型

**当前状态**：**未接入**。环境变量 `VOICE_LLM_API_KEY` / `VOICE_LLM_BASE_URL`
已占位，未设置时云端走降级路径。

接入后要落地的（任务 7.1–7.8）：

- 端侧已判定的意图**跳过模型调用**（省一次调用，省一次延迟）；
- 输出**长度约束**与**重复度检查**（超阈值重生成）；
- **事实性约束**：只允许引用记忆或检索结果中的内容，无来源不编造。

---

## 3. 接自有平台

### 3.1 换云端部署环境

**要改**：`core/cloud/src/main/resources/application.yml`。
所有凭据走环境变量占位，**仓库内不出现真实密钥**。

**验证**：`mvn test`（`HealthControllerTest` 会拉起完整 Spring 上下文）。

### 3.2 接自有模型网关

网关适配属于**基础设施适配**，放 `deploy/gateway/`。

**回流规则**：协议转换逻辑若与业务无关，可以抽成 `core/cloud` 的可插拔适配器，
但必须**转换逻辑与业务逻辑分离**且有独立测试。

**判断标准**：把转换抽到 `core/` 后，它是不是仍然不知道"意图判定"、
"记忆召回"这些业务概念？如果是，就抽得对。

### 3.3 接自有监控

指标定义留在 `core/`（口径由 `core/` 定），采集实现放 `deploy/monitoring/`。

**已定义的指标**见 `core/edge/metrics/collector.py`：

| 指标 | 含义 |
|---|---|
| `vad` | 语音活动判定耗时 |
| `asr` | 端侧识别耗时 |
| `intent` | 意图判定耗时 |
| `round_trip` | 上云往返时延 |
| `first_packet` | 首包延迟 |

**指标口径不要在采集侧改** —— 口径变了，历史数据就不可比了。

### 3.4 接自有设备平台

`device-ref/` 是参考实现。真机对接时：

1. 协议语义**复用** `core/protocol/schema/`，不要另立一套；
2. 端侧行为（降级策略、打断处理）与 `core/edge/` 保持一致；
3. 硬件适配（I2S / DMA / 电源）留在 `device-ref/` 或产品代码里。

---

## 4. 调端侧能力

### 4.1 调 VAD / 断句阈值

**位置**：`core/edge/audio/vad.py`、`core/edge/audio/sentence.py`。

| 参数 | 默认值 | 影响 |
|---|---|---|
| `speech_probability_threshold` | 0.6 | 调高 → 更容易漏掉轻声；调低 → 噪声被当语音 |
| `energy_threshold` | 0.01 | 调高 → 安静环境更稳；调低 → 弱声也能检出 |
| 句末静音 `end_silence_ms` | 600ms | 调长 → 更少误断句，但响应变慢 |
| 换人静音 `turn_silence_ms` | 2000ms | 必须大于句末静音 |

**约束**：`turn_silence_ms > end_silence_ms`，否则构造时直接抛异常
（两者同时到达时行为不确定）。

### 4.2 调降级策略

**位置**：`core/edge/degrade/policy.py`。

| 参数 | 含义 |
|---|---|
| `failure_threshold` | 连续上行失败多少次才降一档 |
| `recovery_success_threshold` | 连续成功多少次才回升一级 |

**回升必须逐级**：一次成功就跳回 `NORMAL` 会导致网络抖动时反复横跳。

### 4.3 调对话策略

**位置**：`core/edge/dialog/phrases.py`（话术分桶）、
`core/edge/dialog/factual.py`（事实性守卫）。

加一类事实性请求：在 `FACTUAL_KEYWORDS` 里追加一个分类与关键词。
**不要**在判定逻辑里加 `if` —— 那个函数是规则表驱动的，加 `if` 会让
"加一类就改一处代码"的性质消失。

### 4.4 怎么验证端侧改动

```powershell
# 单元测试
F:\tools\python313\python.exe -m pytest core\tests\edge -v

# 端到端实测
powershell -ExecutionPolicy Bypass -File core\scripts\start.ps1
F:\tools\python313\python.exe -m core.edge.simulator --url ws://127.0.0.1:8080/voice/uplink --rounds 3
```

**指标采集与报告导出**（任务 5.5 已实现）：

```python
from core.edge.metrics.collector import MetricsCollector
from core.edge.metrics.reporter import MetricsReporter

collector = MetricsCollector()
# ... 采集 ...
report = MetricsReporter(collector).build({"python": "3.13.7"})
print(report.to_markdown())
```

**样本量低于 100 时报告会把该指标标为"样本是否充足：否"** ——
百分位在那时**不具统计意义**，不要拿它当结论。

---

## 5. 改动前的自检清单

照着走，能避开绝大多数坑。

### 通用

- [ ] 先搜过同类抽象，没有新建平行实现
- [ ] 分层依赖未跨层（云端：`Controller → Service → Repository`）
- [ ] 扩展点用接口 + 策略，没有新增 `if (type == X)` 分支
- [ ] 新增公共方法/类有单元测试（happy path + 至少一条失败路径）
- [ ] 命名无拼音、无 `is` 前缀 Boolean 字段
- [ ] 魔法值已常量化/枚举化
- [ ] 日期格式 `yyyy`（小写），金额用 `BigDecimal`
- [ ] `HashMap` 初始化指定容量，没有在 `foreach` 中增删集合
- [ ] `catch` 块有日志或抛出，没有吞掉异常
- [ ] 方法体 ≤ 80 行，公共方法有 Javadoc（`@param` / `@return` / `@throws`）
- [ ] 凭据走环境变量，仓库内无真实密钥

### 协议相关

- [ ] 只改了 `core/protocol/schema/` 一处
- [ ] 共享样例集 `samples.json` 已同步增删
- [ ] `validate-protocol.ps1` 通过
- [ ] Python 与 Java 两侧测试都通过
- [ ] `docs/interface-contract/README.md` 已同步
- [ ] 契约文档与 schema 的一致性测试通过（`test_contract_doc.py`）

### 文档相关

- [ ] `docs/known-limitations.md` 已更新（新增的限制要写清楚是"设计上不支持"还是"尚未实现"）
- [ ] 声称支持的能力**确实验证过**
