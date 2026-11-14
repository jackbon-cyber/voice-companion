# 语音情感陪伴机器人

端云全链路的实现仓库。目标是**陪伴型语音机器人**：用户说话，机器人理解意图、
检索记忆、给出有情感温度的回应。

> **当前阶段：第一阶段（协议契约 + 链路骨架）已完成。**
> 已实测打通**上行链路**（端侧 → 云端）；下行（机器人回话）尚未实现。
> 完整边界见 [`docs/known-limitations.md`](docs/known-limitations.md)。

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
意图在端侧本地执行，无需上云
第 2 轮：识别='今天天气怎么样' 属事实性请求（REALTIME_FACT），引导上云求证，不在端侧作答
第 3 轮：识别='陪我聊会儿天' 意图=unknown 本地处理=False
模拟结束。降级档位：NORMAL
```

云端日志（`core/cloud/logs/backend.out.log`）应出现：

```
会话已注册：session-local-1 → 处理单元 unit-2
会话已回收：session-local-1（原因：simulator_finished）
```

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
│   │   ├── metrics/            # 分段耗时采集与报告导出
│   │   └── simulator.py        # 端侧模拟端主循环
│   ├── cloud/                  # 云端（Spring Boot）
│   │   ├── session/            # 会话注册、粘滞路由、上行通道处理
│   │   ├── protocol/           # Java 侧协议校验
│   │   ├── config/             # Spring 配置
│   │   └── web/                # 健康检查端点
│   ├── scripts/                # start / stop / chroma / fetch-models / validate-protocol
│   └── tests/                  # Python 侧测试
├── device-ref/                 # 设备侧参考实现
├── deploy/                     # 公司私有层（不入库）
└── docs/
    ├── adr/                    # 架构决策记录
    ├── interface-contract/     # 端云接口契约
    ├── deployment.md           # 部署手册
    ├── known-limitations.md    # 已知限制
    └── secondary-development.md # 二次开发指南
```

---

## 文档索引

| 文档 | 读者 | 内容 |
|---|---|---|
| [`core/README.md`](core/README.md) | 使用者 | 前置依赖、启动顺序、常用命令 |
| [`docs/interface-contract/README.md`](docs/interface-contract/README.md) | 端云两侧开发者 | 消息类型、字段语义、兼容性规则 |
| [`docs/adr/README.md`](docs/adr/README.md) | 接手者 | 关键决策的选项/理由/代价 |
| [`docs/deployment.md`](docs/deployment.md) | 部署人员 | 环境变量、端口、排查路径 |
| [`docs/known-limitations.md`](docs/known-limitations.md) | **所有人** | 哪些支持、哪些不支持 |
| [`docs/secondary-development.md`](docs/secondary-development.md) | 二次开发 | 换人设/换模型/接自有平台 |

---

## 验证

```powershell
# 端侧（Python）
F:\tools\python313\python.exe -m pytest core\tests -v

# 云端（Java）
cd core\cloud
$env:JAVA_HOME = 'F:\tools\jdk21\jdk-21.0.13+9'
& 'D:\apache-maven-3.9.2\apache-maven-3.9.2\bin\mvn.cmd' test

# 协议一致性（两侧判定必须相同）
powershell -ExecutionPolicy Bypass -File core\scripts\validate-protocol.ps1
```

---

## 当前能力边界

**已实现并实测**：

- 端云协议契约（8 份 schema，Python/Java 判定一致）
- 端侧音频前端（帧组装、VAD、断句、格式协商）
- 端侧识别适配与拒识、两级意图判定
- 端侧会话状态机与 barge-in 打断
- 端侧降级策略（逐级降级/回升）
- 事实性守卫（端侧不编造具体事实）
- 端侧指标采集与报告导出
- 云端协议校验、会话注册与粘滞路由
- 上行链路端到端实测

**未实现**：云端鉴权、下行语音下发、Redis 会话存储、
云端意图判定与多轮澄清、记忆装配、评测门禁、设备侧固件、真实语音交互。

> **不要声称支持尚未实现的能力。** 逐条边界见
> [`docs/known-limitations.md`](docs/known-limitations.md)。
