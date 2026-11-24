# 部署手册

> 面向**部署人员**，不是面向使用者。使用者看 `core/README.md`。
>
> 本手册覆盖的是**当前已实现**的部分。尚未实现的能力（云端鉴权、下行下发、
> Redis 会话存储等）见 `docs/known-limitations.md`，**不要按它们规划生产部署**。

**先看哪一份**：

- **第一次上手、要从头跑起来** → `docs/operations-manual.md`
  （第 0 章 10 分钟跑通，第 3 章接真实设备，第 4 章部署到服务器）
- **已经把平台跑起来了、只是要部署** → 继续看本文
- **接真实设备** → `docs/operations-manual.md` 第 3 章
  （含协议样例、固件接口清单、行为契约与验收清单）

---

## 1. 部署形态

当前形态是**单机部署**：ChromaDB、嵌入服务、云端后端、端侧模拟端都跑在一台机器上。

```
┌─────────────────────────────────────────────────────┐
│  单机                                                │
│                                                      │
│  ┌──────────────┐      ┌────────────────────┐       │
│  │ ChromaDB     │◄─────┤ 云端后端            │       │
│  │ :8765        │      │ :8080              │       │
│  └──────────────┘      │  ├ /api/health     │       │
│                        │  └ /voice/uplink   │       │
│   ┌──────────────┐     └────────────────────┘       │
│   │ 嵌入服务     │◄─────────┘                     │
│   │ :8766        │            ▲                   │
│   └──────────────┘            │ WebSocket        │
│                        ┌─────┴──────────┐          │
│                        │ 端侧模拟端      │          │
│                        │ (Python)       │          │
│                        └────────────────┘          │
└─────────────────────────────────────────────────────┘
```

> ★ **嵌入服务（:8766）不是可选组件**。
> 云端收到上行消息后会**同步**调它算记忆向量，
> 它不可用时记忆写入和下行回复**直接失败**（不是降级）。
> 实测日志：`记忆写入失败，已忽略：local embedding connect failed for http://127.0.0.1:8766/v1/embeddings`
> —— 表现为"机器人完全不回话"，且日志只有一行 WARN，极易误判为网络问题。
> 详见 `operations-manual.md` 2.1。

**当前不支持**：多实例部署、负载均衡、跨机部署。
云端的会话注册表是**进程内**的，多实例之间不共享（见已知限制 2.2）。

---

## 2. 环境变量清单

**仓库内不出现任何真实凭据。** 全部通过环境变量注入。

| 变量 | 必填 | 默认值 | 说明 | 未设置的后果 |
|---|---|---|---|---|
| `JAVA_HOME` | 是 | `F:\tools\jdk21\jdk-21.0.13+9` | JDK 21 路径 | 用 JDK 17 编译失败（class file 61.0 vs 65.0） |
| `VOICE_CHROMA_BASE_URL` | 否 | `http://127.0.0.1:8765` | ChromaDB 地址 | 云端启动时连通性检查失败 |
| `VOICE_CHROMA_DATA_PATH` | 否 | `data/chroma` | ChromaDB 数据目录 | 数据落在默认位置 |
| `VOICE_UPLINK_TOKEN` | **生产必填** | 空 | 上行通道接入凭据 | **不启用鉴权，任何客户端都能接入上行通道** |
| `VOICE_SESSION_HEARTBEAT_TIMEOUT_MS` | 否 | `90000` | 心跳超时阈值（毫秒） | 端侧断网后会话长时间不被回收，占住处理单元内存 |
| `VOICE_SESSION_SCAN_INTERVAL_MS` | 否 | `30000` | 会话扫描间隔（毫秒） | 超时回收的检测延迟变大 |
| `VOICE_LLM_BASE_URL` | 否 | 空 | 大模型服务地址（OpenAI 兼容，需含 `/chat/completions` 的基址） | 云端回复走模板路径（**默认行为，不影响可用性**） |
| `VOICE_LLM_API_KEY` | 否 | 空 | 大模型 API Key | 同上 |
| `VOICE_LLM_MODEL` | 否 | `qwen-plus` | 模型名称（已实测选型，见已知限制 2.15） | 用默认模型名请求 |
| `VOICE_LLM_TIMEOUT_SECONDS` | 否 | `15` | 单次请求超时秒数 | 超时后立刻退回模板 |
| `VOICE_LLM_MAX_TOKENS` | 否 | `200` | 单次生成的最大 token 数 | 可能截断长回复 |
| `VOICE_MQTT_HOST` | 否 | `127.0.0.1` | MQTT Broker 地址 | 控制通道不可用 |
| `VOICE_MQTT_PORT` | 否 | `1883` | MQTT Broker 端口 | 同上 |

**设置方式**（PowerShell，永久生效）：

```powershell
[Environment]::SetEnvironmentVariable('VOICE_CHROMA_BASE_URL', 'http://127.0.0.1:8765', 'User')
[Environment]::SetEnvironmentVariable('VOICE_UPLINK_TOKEN', '<你的接入凭据>', 'User')
```

> **`VOICE_UPLINK_TOKEN` 未设置时上行通道不鉴权。** 这是开发期的默认形态，
> 让"克隆下来就能跑"成立；生产部署**必须**设置，否则任何客户端都能接入上行通道。
> 凭据通过请求头 `Authorization: Bearer <token>` 传递，也支持查询参数 `?token=`。

> **大模型是可选增强，不是必需依赖。** `VOICE_LLM_BASE_URL` 与 `VOICE_LLM_API_KEY`
> **两者都设置**才启用大模型路径；只设其一多半是配置写错了，
> 此时直接走模板路径而不是发起注定失败的请求。
> 大模型的失败（超时、5xx、响应不可解析）在服务内部被兜住，
> 自动退回模板，**不会中断对话**。
>
> 启用后**记忆的选择仍然由相关性准入策略决定**，大模型只负责把已选定好的
> 记忆内容改写成更自然的表达；**引用来源（`citations`）仍由代码填充**，
> 不由模型生成 —— 这是跨用户隔离断言得以成立的前提。

---

## 3. 端口与资源

| 服务 | 端口 | 协议 | 资源需求 |
|---|---|---|---|
| ChromaDB | 8765 | HTTP | 内存 ≥ 512MB；磁盘按数据量 |
| 嵌入服务 | 8766 | HTTP（OpenAI 兼容 `/v1/embeddings`） | 内存 ≥ 512MB（ONNX 运行时） |
| 云端后端 | 8080 | HTTP + WebSocket | JVM 堆 ≥ 512MB；磁盘 ≥ 200MB |
| 端侧模拟端 | 无（出站连接） | WebSocket 客户端 | 内存 ≥ 256MB |
| MQTT Broker | 1883 | MQTT | 外部依赖，当前未纳入启动脚本 |

**当前无 GPU 需求** —— 云端尚未接入大模型，端侧模型为可选。

### 资源实测

| 场景 | 内存 | 说明 |
|---|---|---|
| 仅 ChromaDB + 云端后端（空闲） | 约 700MB | JVM 默认堆 + Chroma 常驻 |
| 加嵌入服务（ONNX，22.9MB 模型） | 约 1.2GB | 容器形态实测，需重新标定 |
| 加端侧模拟端（无模型） | 约 900MB | |
| 加端侧模拟端（有 Whisper base） | 约 1.5GB | 未实测，估算值，需实测替换 |

> 上表除前两行外均为估算。**实测值应替换估算值**（见已知限制 2.11）。

---

## 3.1 ★ 目标机前置要求（Linux 实测结论）

> 本节是**部署实测**补上的。原手册只列了软件版本，
> 没说明目标机要满足什么条件 —— 实测踩到的坑记在这里。

| 项 | 要求 | 不满足时的现象 |
|---|---|---|
| Python | **3.13**（且发行版装得下） | `Could not find a version that satisfies the requirement chromadb==1.0.0`（可用版本只到 0.5.23）。**报错完全没提 Python 版本**，极易误判为 pip 源问题或版本号写错 |
| C++ 编译器 | `build-essential`（gcc/g++/make） | `RuntimeError: Unsupported compiler -- at least C++11 support is needed!` —— **极具误导性**：听起来像"编译器版本太老"，真相是**一个编译器都没有** |
| JDK | 21 | 用 JDK 17 运行会报 `class file version 61.0 vs 65.0` |

**发行版实测对照**：

| 目标机 | 装 ChromaDB 1.0 |
|---|---|
| Ubuntu 20.04（Python 3.8） | ✗ 装不上 |
| Debian 13 / Ubuntu 24.04 / `python:3.13-slim` | ✓ 正常 |

**为什么 ChromaDB 1.0 需要编译器**：`chroma-hnswlib` 在 Python 3.13 上
没有预编译 wheel，只能本地编译。

**协议 schema 必须随 jar 分发**：打包时若漏配 `resources`，
jar 里就没有 schema，云端会**启动失败**并列出缺哪几个
（不是静默降级 —— 详见 `operations-manual.md` 4.8.3）。部署后建议核一次：

```bash
jar tf core/cloud/target/voice-cloud-0.0.1-SNAPSHOT.jar | grep protocol/schema
```

---

## 4. 模型清单

**两个端侧模型都是可选的**，缺失时端侧自动降级：

| 模型 | 大小 | 用途 | 缺失时的降级行为 | 获取方式 |
|---|---|---|---|---|
| `faster-whisper-base` | 约 150MB | 端侧 ASR | `NullRecognizer`（识别不出文字），意图只能靠规则表命中 | `fetch-models.ps1 -Target asr` |
| `Qwen2.5-0.5B-Instruct-Q4_K_M.gguf` | 约 400MB | 端侧对话 | 话术库（固定话术，不结合上下文） | `fetch-models.ps1 -Target llm` |

模型落在 `core/models/`，**不入库**（见 ADR-006）。

**完整性校验**：下载后 sha256 记入 `core/models/SHA256SUMS`，
下次运行 `fetch-models.ps1` 时强制比对。**不匹配会重新下载** ——
下载损坏的模型表现为"识别效果差"，极难排查，因此这一层校验不能省。

**生产环境建议**：把权重分发到内网制品库，而非每个部署点都从公网镜像拉。

---

## 5. 启动顺序

**顺序是固定的**：

```
ChromaDB → 嵌入服务 → 云端后端 → 端侧模拟端
```

Chroma 必须先于后端起来 —— 后端启动时做一次 Chroma 连通性检查，
Chroma 没就绪会让后端启动失败。

```powershell
# 1. 起 ChromaDB + 云端后端（脚本会自动等待两个健康检查通过）
powershell -ExecutionPolicy Bypass -File core\scripts\start.ps1

# 2. 起端侧模拟端（另开一个终端，在仓库根执行）
F:\tools\python313\python.exe -m core.edge.simulator --url ws://127.0.0.1:8080/voice/uplink

# 3. 停环境
powershell -ExecutionPolicy Bypass -File core\scripts\stop.ps1
```

**为什么端侧要"在仓库根执行"**：端侧代码位于 `core/` 包下，
模块全名是 `core.edge.simulator`。在 `core/` 目录里执行
`python -m edge.simulator` 会因包路径不对而失败。

### 分步启动（排障用）

```powershell
# 只起 Chroma
powershell -ExecutionPolicy Bypass -File core\scripts\chroma.ps1 start
powershell -ExecutionPolicy Bypass -File core\scripts\chroma.ps1 status

# 只起后端（假定 Chroma 已在跑）
powershell -ExecutionPolicy Bypass -File core\scripts\start.ps1 -SkipChroma

# 只起 Chroma，不起后端
powershell -ExecutionPolicy Bypass -File core\scripts\start.ps1 -SkipBackend
```

---

## 6. 健康检查

| 检查项 | 地址 | 期望响应 | 检查时机 |
|---|---|---|---|
| ChromaDB | `http://127.0.0.1:8765/api/v2/version` | HTTP 200 | `start.ps1` 自动等待 |
| 嵌入服务 | `http://127.0.0.1:8766/v1/health` | HTTP 200 | 部署脚本自动等待 |
| 云端后端 | `http://127.0.0.1:8080/api/health` | `{"status":"UP"}` | `start.ps1` 自动等待 |
| 上行通道 | `ws://127.0.0.1:8080/voice/uplink` | 连接成功 | 端侧连接时验证 |

**注意 `/api/health` 只检查进程存活**，不检查 Chroma 连通性 ——
Chroma 挂了后端仍会报 UP。需要更严格的探针时应新增端点。

---

## 7. 日志

| 日志 | 位置 | 内容 |
|---|---|---|
| 云端后端 | `core/cloud/logs/backend.out.log` | Spring Boot 全量输出 |
| 云端后端错误 | `core/cloud/logs/backend.err.log` | 标准错误流 |
| 端侧模拟端 | 控制台 | 通过 `logging` 模块输出 |

**`logs/` 已在 `.gitignore` 中**，不会入库。

**排查云端问题时第一件事**：看 `core/cloud/logs/backend.out.log`。
`start.ps1` 以隐藏窗口 + 重定向方式启动后端，
日志不落盘就完全看不到后端的任何状态。

---

## 8. 排查路径

按现象定位：

| 现象 | 先看 | 常见原因 |
|---|---|---|
| `start.ps1` 报 Chroma 未就绪 | `chroma.ps1 status` | 8765 被占用；`data/chroma` 目录权限 |
| `start.ps1` 报后端未就绪 | `core/cloud/logs/backend.out.log` | JDK 版本不对（须 21）；Maven 仓库路径；Chroma 未起 |
| 端侧报"上行链路失败" | 后端日志 | 8080 未起；后端已崩 |
| 端侧一直"识别不可信" | — | 正常：真实识别需要模型权重，模拟端用脚本识别器 |
| 端侧报协议校验失败 | 后端日志 | 两侧 schema 版本不一致 —— 跑 `validate-protocol.ps1` |
| 会话注册了但没回收 | 后端日志 | 心跳超时的定时扫描未实现（已知限制 2.4） |

### 协议不一致的排查

两侧判定分歧是最难查的一类问题。**先跑协议校验**：

```powershell
powershell -ExecutionPolicy Bypass -File core\scripts\validate-protocol.ps1
```

- 校验**通过**但线上不一致 → 两侧收到的字节不同（编码、截断、大小写）
- 校验**失败** → schema 与样例不一致，按输出逐条修

---

## 9. 卸载

```powershell
# 停服务
powershell -ExecutionPolicy Bypass -File core\scripts\stop.ps1

# 删数据（Chroma 数据目录）
Remove-Item -Recurse -Force data\chroma

# 删模型
Remove-Item -Recurse -Force core\models
```

`data/` 与 `core/models/` 都在 `.gitignore` 中，卸载时一并清理即可。

---

## 10. 生产部署前的待办

**当前形态不能直接上生产。** 上生产前至少要完成：

| 项 | 依据 |
|---|---|
| 云端鉴权（任何能连到端口的客户端都能建会话） | 已知限制 2.1 |
| 下行语音下发（当前机器人不回话） | 已知限制 2.6 |
| 会话状态外置（Redis）+ 一致性哈希环 | 已知限制 2.2 |
| 心跳超时扫描的定时器 | 已知限制 2.4 |
| 真实模型实测数据替换估算值 | 已知限制 2.11 |
| 评测门禁接入 CI | OpenSpec 任务 10.4 |
| ADR 补充部署相关的决策（副本数、探针、日志采集） | `docs/adr/README.md` |
