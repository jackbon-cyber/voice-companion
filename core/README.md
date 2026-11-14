# 语音情感陪伴机器人 · 核心工程

端云全链路的第一阶段实现：协议契约、端侧 PC 模拟端、云端接入与会话粘滞。

> **本仓库是三仓结构的第一层**（开源层）。完整结构见仓库根 `README`。
> 公司交付物（部署清单、客户培训材料等）不在本仓。

---

## 前置依赖

| 组件 | 版本 | 本机路径 | 说明 |
|---|---|---|---|
| JDK | 21 | `F:\tools\jdk21\jdk-21.0.13+9` | 必须 21；用 17 会编译失败（class file 61.0 vs 65.0） |
| Maven | 3.9 | `D:\apache-maven-3.9.2\apache-maven-3.9.2` | 本地仓库在 `F:\tools\maven-repo`（C 盘空间不足） |
| Python | 3.13 | `F:\tools\python313\python.exe` | 3.10 装不上 chromadb 1.5.9 |
| ChromaDB | 1.5.9 | 由 `scripts/chroma.ps1` 管理 | 监听 `127.0.0.1:8765` |

**Python 依赖安装**

```powershell
F:\tools\python313\python.exe -m pip install -r core\requirements.txt
```

**Maven 本地仓库**：已配置在 `settings.xml` 的 `<localRepository>`，指向 `F:\tools\maven-repo`。

---

## 环境变量

仓库内**不出现任何真实凭据**。以下全部通过环境变量注入，未设置时使用占位默认值：

| 变量 | 用途 | 默认值 |
|---|---|---|
| `JAVA_HOME` | JDK 21 路径 | `F:\tools\jdk21\jdk-21.0.13+9` |
| `VOICE_CHROMA_BASE_URL` | Chroma 服务地址 | `http://127.0.0.1:8765` |
| `VOICE_CHROMA_DATA_PATH` | Chroma 数据目录 | `data/chroma` |
| `VOICE_LLM_API_KEY` | 云端大模型 API Key | 空（未设置时云端走降级路径） |
| `VOICE_LLM_BASE_URL` | 大模型服务地址 | 空 |
| `VOICE_MQTT_HOST` | MQTT Broker 地址 | `127.0.0.1` |
| `VOICE_MQTT_PORT` | MQTT Broker 端口 | `1883` |

---

## 启动顺序

**顺序是固定的**：ChromaDB → 云端后端 → 端侧模拟端。

Chroma 必须先于后端起来 —— 后端启动时做一次 Chroma 连通性检查，Chroma 没就绪会让后端启动失败。

```powershell
# 1. 起 ChromaDB + 云端后端（自动等待两个健康检查通过）
powershell -ExecutionPolicy Bypass -File core/scripts/start.ps1

# 2. 起端侧模拟端（另开一个终端，在仓库根执行）
F:\tools\python313\python.exe -m core.edge.simulator --url ws://127.0.0.1:8080/voice/uplink

# 3. 停环境
powershell -ExecutionPolicy Bypass -File core/scripts/stop.ps1
```

> **为什么在仓库根执行**：端侧代码位于 `core/` 包下，模块全名是 `core.edge.simulator`。
> 在 `core/` 目录里执行 `python -m edge.simulator` 会因包路径不对而失败。
>
> **端侧模拟端做了什么**：不接真实麦克风与扬声器。它生成一段模拟音频驱动
> VAD 与断句，经端侧识别与意图判定后上行，等待云端回复，最后发出会话结束消息
> —— 端云**双向**链路的骨架是通的，但**没有真实语音交互**。
> 模拟端的识别走 `ScriptedRecognizer`（按脚本返回文本），
> 目的是让识别 → 意图 → 上行 → 回复这条链路能被演示；
> 生产路径用的是 `FasterWhisperRecognizer` / `NullRecognizer`。
> 接上真实麦克风与 TTS 播放属第二阶段。
>
> **能演示的三条路径**：
> - 固定指令（如"把音量调到五十"）→ 端侧规则命中，本地执行，**不上行**；
> - 事实性请求（如"今天天气怎么样"）→ 端侧**不编造**，引导上云求证；
> - 开放闲聊（如"陪我聊会儿天"）→ 判为长尾意图，上云由云端处理。
>
> **回复内容是占位话术**：云端目前只回固定的两句话，
> 真实的记忆检索与意图编排属后续阶段。

---

## 常用命令

### 端侧（Python）

```powershell
# 在仓库根执行
F:\tools\python313\python.exe -m pytest core\tests -v

# 只跑协议相关
F:\tools\python313\python.exe -m pytest core\tests\protocol -v

# 只跑跨语言契约一致性
F:\tools\python313\python.exe -m pytest core\tests\protocol\test_cross_language_consistency.py -v

# 只跑契约文档与 schema 的一致性检查
F:\tools\python313\python.exe -m pytest core\tests\protocol\test_contract_doc.py -v
```

### 协议校验（端云两侧）

```powershell
# 校验全部 schema 与共享样例
powershell -ExecutionPolicy Bypass -File core\scripts\validate-protocol.ps1

# 只做 schema 自检
powershell -ExecutionPolicy Bypass -File core\scripts\validate-protocol.ps1 -SchemaOnly
```

### 云端（Java）

```powershell
cd core\cloud
$env:JAVA_HOME = 'F:\tools\jdk21\jdk-21.0.13+9'

# 跑全部测试
& 'D:\apache-maven-3.9.2\apache-maven-3.9.2\bin\mvn.cmd' test

# 只跑协议校验
& 'D:\apache-maven-3.9.2\apache-maven-3.9.2\bin\mvn.cmd' test -Dtest=ProtocolValidatorTest
```

### ChromaDB

```powershell
powershell -ExecutionPolicy Bypass -File core/scripts/chroma.ps1 start
powershell -ExecutionPolicy Bypass -File core/scripts/chroma.ps1 status
powershell -ExecutionPolicy Bypass -File core/scripts/chroma.ps1 stop
```

### 模型

```powershell
powershell -ExecutionPolicy Bypass -File core/scripts/fetch-models.ps1
```

---

## 不装模型也能跑

**两个端侧模型都是可选的**，缺失时自动降级，端侧不会崩溃：

| 缺失的模型 | 降级行为 | 用户可见影响 |
|---|---|---|
| `faster-whisper`（端侧 ASR） | 走 `NullRecognizer` | 端侧不再识别语音，意图只能靠规则表命中 |
| `Qwen2.5-0.5B`（端侧对话） | 走话术库 | 回复变成固定话术，不结合上下文 |

因此在一台**没有模型、没有网络的机器**上，本工程依然能完成一轮本地应答 —— 这也是第一阶段把「零硬件可跑通」当作硬指标的原因。

---

## 目录结构

```
core/
├── protocol/                 # 端云协议契约（JSON Schema，Python 与 Java 共用同一份）
│   ├── loader.py
│   ├── validator.py          # 统一校验入口（离线解析 $ref）
│   └── schema/               # 8 份 schema
├── edge/                     # 端侧
│   ├── audio/                # 帧组装、格式协商、VAD、断句
│   ├── asr/                  # 识别适配层与拒识
│   ├── intent/               # 两级意图判定
│   ├── dialog/               # 本地兜底对话与事实性守卫
│   ├── session/              # 端侧会话状态机与 barge-in 打断
│   ├── degrade/              # 降级档位策略
│   ├── transport/            # 上行通道、下行通道与控制通道
│   ├── metrics/              # 分段耗时采集与报告导出
│   └── simulator.py          # 端侧模拟端主循环
├── cloud/                    # 云端（Spring Boot 3.3.5 / Java 21）
│   ├── session/              # 会话注册、粘滞路由、上行通道处理
│   ├── downlink/             # 下行消息发布（首包/末包标记、序号连续）
│   ├── reply/                # 下行回复编排
│   ├── protocol/             # Java 侧协议校验
│   ├── config/               # Spring 配置
│   └── web/                  # 健康检查端点
├── scripts/                  # chroma / start / stop / fetch-models / validate-protocol
├── tests/                    # Python 侧测试
└── requirements.txt
```

---

## 协议一致性怎么保证

端云两侧读**同一份** schema 文件（`core/protocol/schema/`），不各写一份。

`core/cloud/src/test/resources/protocol-samples/samples.json` 是**唯一一份**样例数据，
Python 侧与 Java 侧各自遍历它，断言对每条样例的判定结论完全一致：

```powershell
# Python 侧
F:\tools\python313\python.exe -m pytest core\tests\protocol\test_cross_language_consistency.py -v

# Java 侧
& 'D:\apache-maven-3.9.2\apache-maven-3.9.2\bin\mvn.cmd' test -Dtest=ProtocolValidatorTest
```

两侧任一改动导致判定漂移，两个命令里至少有一个会失败。
