# 语音情感陪伴机器人

端云全链路的实现仓库。目标是**陪伴型语音机器人**：用户说话，机器人理解意图、
检索记忆、给出有情感温度的回应。

> **当前阶段：第一阶段收口（协议契约 + 记忆能力 + 评测门禁）已完成。**
> 端云**双向链路**已实测打通；**意图三级判定、长期记忆、记忆作答、
> 安全审核、多轮澄清、评测门禁**均已实现并通过门禁。
> 云端回复由**代码选取记忆 + 模板引用**生成，配置大模型后措辞可改写。
> 完整边界见 [`docs/known-limitations.md`](docs/known-limitations.md)。

## 实测指标

以下数字来自一次实际运行（`core/scripts/eval.ps1` + `core/scripts/e2e.ps1`），
可用同一脚本复现：

| 维度 | 实测 | 阈值 | 样本 |
|---|---|---|---|
| 意图分类准确率 | 100.0% | ≥ 85% | 15 |
| 长期记忆召回 Recall@K | 100.0% | ≥ 90% | 13 |
| 记忆作答准确率 | 100.0% | ≥ 95% | 10 |
| 记忆作答率（覆盖率） | 76.9% | ≥ 75% | 13 |
| 记忆编造率 | 0.0% | ≤ 5% | 13 |
| 安全策略召回率 | 100.0% | ≥ 95% | 13 |
| 情感标签判定 | 80.0% | ≥ 75% | 10 |
| 端侧识别准确率（安静 30dB） | 85.7% | ≥ 80% | 14 |
| 端到端隔离与降级断言 | 8/8 通过 | 全过 | 8 |

> **这些数字证明什么、不证明什么**，逐条写在
> [`docs/known-limitations.md`](docs/known-limitations.md)。
> 最重要的一条：端侧识别评测的音频**目前全部是 TTS 合成**，
> 因此 mild/noisy 两档**不参与门禁判定** —— 真人语音的噪声鲁棒性**尚未验证**。


---

## 三仓结构

| 仓库 / 目录 | 内容 | 许可 |
|---|---|---|
| `core/` | 协议契约、PC 模拟端、云端接入与会话、评测门禁 | MIT（本仓库） |
| `device-ref/` | STM32 固件骨架、模型包格式、OTA 脚本 | 参考实现 |
| `deploy/` | 公司内网网关适配、GPU 编排、监控接入 | **私有，不入库** |

分层的判据是**可复现性**：能独立复现核心能力的进开源仓库，
只在本司环境成立的留在私有层。详见
[`docs/adr/README.md`](docs/adr/README.md) 的 ADR-002。

---

## 十分钟跑通

```powershell
# 1. 起 ChromaDB + 云端后端（自动等待两个健康检查通过）
powershell -ExecutionPolicy Bypass -File core\scripts\start.ps1

# 2. 起端侧模拟端（另开一个终端，在仓库根执行）
F:\tools\python313\python.exe -m core.edge.simulator --url ws://127.0.0.1:8080/voice/uplink

# 3. 停环境
powershell -ExecutionPolicy Bypass -File core\scripts\stop.ps1
```

预期输出：

```
已连接云端并开始会话：ws://127.0.0.1:8080/voice/uplink
第 1 轮：识别='把音量调到五十' 意图=set_volume 本地处理=True
意图在端侧本地执行，不上行
第 1 轮：本地产生应答='还有别的想说的吗？'（情感=neutral 离线=False 来源=LOCAL）
第 2 轮：识别='今天发生了好多事情啊' 意图=unknown 本地处理=False
收到云端回复：'我这边还没有关于这件事的记录，你说得再具体一点我就能记下了。'（情感=tenderness）
模拟结束。降级档位：NORMAL
本轮共产生 1 条本地应答（来源均为 LOCAL，未伪装为云端回复）
```

云端日志（`core/cloud/logs/backend.out.log`）应出现：

```
会话已注册：session-local-1 → 处理单元 unit-2
下发回复：会话=session-local-1 意图=unknown 本地已处理=false
会话已回收：session-local-1（原因：simulator_finished）
```

> **注意**：云端回复走**记忆检索 → 引用来源 → 措辞**三步。
> 检索不到支撑记忆时**如实说"没有记录"而不是编造** ——
> 这正是评测里"记忆编造率 0%"这条门禁要守住的东西。
> 配置大模型凭据后，措辞可由模型改写，但**记忆选择与引用来源仍由代码决定**
> （见 [`docs/known-limitations.md`](docs/known-limitations.md)）。

**前置依赖**（本机路径）：

| 组件 | 版本 | 路径 |
|---|---|---|
| JDK | 21 | `F:\tools\jdk21\jdk-21.0.13+9` |
| Maven | 3.9 | `D:\apache-maven-3.9.2\apache-maven-3.9.2` |
| Python | 3.13 | `F:\tools\python313\python.exe` |

---

## 技术栈

| 层 | 技术 | 理由 |
|---|---|---|
| 云端 | Java 21 / Spring Boot 3.3.5 | 复用公司已有的记忆资产（`agent-memory-kb`） |
| 端侧 | Python 3.13 | `faster-whisper` / `llama-cpp-python` / `paho-mqtt` 生态 |
| 协议 | JSON Schema Draft 2020-12 | 两侧共用一份，无需代码生成 |
| 向量库 | ChromaDB 1.5.9 | 沿用上游 |

**为什么是混合语言**：端云两侧不共享代码，只共享协议 ——
跨语言反而逼着协议设计更严谨。详见 ADR-003。

---

## 目录结构

```
voice-companion/
├── core/                       # 开源层（MIT）
│   ├── protocol/               # 端云协议契约（8 份 schema，Python/Java 共用）
│   ├── edge/                   # 端侧（Python）
│   │   ├── audio/              # 帧组装、格式协商、VAD、断句
│   │   ├── asr/                # 识别适配层与拒识
│   │   ├── intent/             # 两级意图判定
│   │   ├── dialog/             # 本地兜底对话与事实性守卫
│   │   ├── session/            # 会话状态机与 barge-in 打断
│   │   ├── degrade/            # 降级档位策略
│   │   ├── transport/          # 上行通道与控制通道
│   │   ├── embedding/          # 本地 ONNX 嵌入服务
│   │   ├── metrics/            # 分段耗时采集与报告导出
│   │   └── simulator.py        # 端侧模拟端主循环
│   ├── cloud/                  # 云端（Spring Boot）
│   │   ├── session/            # 会话注册、粘滞路由、上行通道处理
│   │   ├── memory/             # 记忆层：装配、更新、召回、画像、隔离
│   │   ├── intent/             # 三级意图判定与原型最近邻分类器
│   │   ├── agent/              # 子智能体框架、多轮澄清、输出治理
│   │   ├── safety/             # 安全审核、危机干预、句级流审
│   │   ├── reply/              # 记忆支撑回复与措辞改写
│   │   ├── auth/               # 握手鉴权
│   │   ├── chroma/             # 向量库接入
│   │   ├── eval/               # 评测执行器与门禁常量
│   │   ├── protocol/           # Java 侧协议校验
│   │   ├── config/             # Spring 配置
│   │   └── web/                # 健康检查端点
│   ├── eval/                   # 评测集（源文件）与端侧识别评测
│   ├── e2e/                    # 端到端隔离与降级断言
│   ├── scripts/                # start / stop / chroma / fetch-models /
│   │                           # validate-protocol / eval / e2e
│   └── tests/                  # Python 侧测试
├── device-ref/                 # 设备侧参考实现（固件骨架、模型包、OTA）
├── deploy/                     # 公司私有层（不入库）
└── docs/
    ├── adr/                    # 架构决策记录
    ├── architecture/           # 技术架构方案（11 章 + 5 附录）源文件
    ├── interface-contract/     # 端云接口契约
    ├── operations-manual.md    # 操作手册：上手、接真机、部署、排障
    ├── deployment.md           # 部署手册
    ├── known-limitations.md    # 已知限制
    ├── real-recording-handover.md # 真人录音接入交接单
    └── secondary-development.md # 二次开发指南
```

---

## 文档索引

| 文档 | 读者 | 内容 |
|---|---|---|
| [`docs/operations-manual.md`](docs/operations-manual.md) | **第一次上手的人** | 10 分钟跑通 → 接真实设备（分 5 步）→ 部署到服务器 → 排障手册 |
| [`core/README.md`](core/README.md) | 使用者 | 前置依赖、启动顺序、常用命令 |
| [`docs/interface-contract/README.md`](docs/interface-contract/README.md) | 端云两侧开发者 | 消息类型、字段语义、兼容性规则 |
| [`docs/adr/README.md`](docs/adr/README.md) | 接手者 | 关键决策的选项/理由/代价 |
| [`docs/deployment.md`](docs/deployment.md) | 部署人员 | 环境变量、端口、排查路径 |
| [`docs/known-limitations.md`](docs/known-limitations.md) | **所有人** | 哪些支持、哪些不支持 |
| [`docs/secondary-development.md`](docs/secondary-development.md) | 二次开发 | 换人设/换模型/接自有平台 |
| [`docs/real-recording-handover.md`](docs/real-recording-handover.md) | 录真人语音的人 | 录音要求、命名规则、到位后要重跑什么 |
| [`docs/architecture/README.md`](docs/architecture/README.md) | 架构评审 | 端云协同技术架构方案（11 章 + 5 附录）及其构建方式 |
| [`docs/github-publish-guide.md`](docs/github-publish-guide.md) | 发布者 | 推到 GitHub 的完整步骤与必须勾选的仓库设置 |
| [`docs/adr/README.md`](docs/adr/README.md) | 接手者 | 关键决策的选项/理由/代价 |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | 贡献者 | 怎么把改动交进来，哪些改动会让门禁失败 |
| [`SECURITY.md`](SECURITY.md) | 报告问题的人 | 私下报告渠道 + 当前安全边界（含未实现项） |
| [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) | 所有人 | 参与讨论的底线 |
| [`CHANGELOG.md`](CHANGELOG.md) | 所有人 | 可验证的进展记录 |

---

## 验证

```powershell
# 端侧（Python）—— 518 项
F:\tools\python313\python.exe -m pytest core\tests -v

# 云端（Java）—— 357 项
cd core\cloud
$env:JAVA_HOME = 'F:\tools\jdk21\jdk-21.0.13+9'
& 'D:\apache-maven-3.9.2\apache-maven-3.9.2\bin\mvn.cmd' test

# 协议一致性（两侧判定必须相同）
powershell -ExecutionPolicy Bypass -File core\scripts\validate-protocol.ps1

# 端到端门禁（隔离 + 降级断言，需要服务在跑）
powershell -ExecutionPolicy Bypass -File core\scripts\e2e.ps1

# 评测门禁（六个维度）
powershell -ExecutionPolicy Bypass -File core\scripts\eval.ps1
```

> 门禁退出码约定：`0` 通过 / `1` 未达标 / `2` 环境不可用 / `3` 执行异常
> （[ADR-010](docs/adr/README.md)）。

---

## 参与贡献

- 想提改动：[`CONTRIBUTING.md`](CONTRIBUTING.md) —— 提交前自检清单、
  改动规约、提交信息规范、PR 模板。
- 发现安全问题：[`SECURITY.md`](SECURITY.md) —— **私下报告**，不要开公开 issue；
  该文件同时**主动披露**了当前未实现的安全能力。
- 参与讨论：[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)。

## 许可

[MIT](LICENSE) —— 见 `LICENSE` 文件。
`deploy/` 层为公司内网私有实现，**不入库**，
不随本仓库的许可分发（见 [ADR-002](docs/adr/README.md)）。

## 当前能力边界

**已实现并实测**：

- 端云协议契约（8 份 schema，Python/Java 判定一致，28 条样例全过）
- 端侧音频前端（帧组装、VAD、断句、格式协商）
- 端侧识别适配与拒识、两级意图判定
- 端侧会话状态机与 barge-in 打断
- 端侧降级策略（逐级降级/回升）
- 事实性守卫（端侧不编造具体事实）
- 端侧指标采集与报告导出
- 云端协议校验、会话注册与粘滞路由、心跳扫描、定时重路由
- 下行发布（首包/末包标记、序号连续、发布前协议校验）与端侧下行接收
- **云端鉴权**（握手阶段 Bearer 校验，常量时间比较）
- **三级意图判定**（规则 + 原型最近邻 + 云端长尾）
- **多轮澄清与输出治理**
- **记忆能力**：会话上下文装配、记忆更新（覆盖加归档）、冲突消解、
  倒数排名融合、三路并行召回、用户画像五维、分片嵌入、
  **跨用户隔离的存储层强制**
- **记忆作答**：检索 → 引用来源 → 措辞，检索不到支撑记忆时如实拒答
- **安全审核、危机干预、句级流审、云端降级**
- **评测门禁**（六个维度 + 端到端 8 项断言，阈值集中在单一常量模块）
- **设备侧固件骨架、模型包格式、OTA 流程编排**（参考实现）
- **双向链路端到端实测**（上行 + 下行回复一一对应）

**未实现**（逐条边界与验证方式见
[`docs/known-limitations.md`](docs/known-limitations.md)）：

- 令牌签发/过期/轮换/吊销、多租户身份携带
- 端到端加密、速率限制、集中审计
- Redis 会话存储（当前进程内）
- 真实 TTS 音频与真人语音交互
- 大模型生成质量指标（**当前任何 LLM 相关指标都未验证**）

**未验证**（有实现，但没有证据）：

- 真人语音的噪声鲁棒性与远场拾音 —— 评测音频目前全为 TTS 合成，
  mild/noisy 两档**不作门禁依据**
- 长尾意图的云端大模型处理效果
- 多轮对话中的情绪转折与澄清策略
- 端到端延迟与并发承载能力
- 记忆检索的规模化表现（相关性下限两侧仅 0.0039 余量，样本 13 + 13 条）
- STM32 真机上的全部能力

> **不要声称支持尚未实现的能力。** 逐条边界见
> [`docs/known-limitations.md`](docs/known-limitations.md)。
