# 贡献指南（Contributing）

感谢你愿意花时间参与这个项目。本文件说明**怎么把改动交进来**，
以及**哪些改动会让门禁失败** —— 后者比前者更重要。

> 本项目有一条硬规矩：**不要声称支持尚未实现的能力。**
> 每一处"已支持"都必须有对应的可复现验证手段。
> 详见 [`docs/known-limitations.md`](docs/known-limitations.md)。

---

## 一、先读这个：仓库的三层结构

改动落在哪一层，决定了它要不要入库。

| 层 | 目录 | 是否入库 | 判据 |
|---|---|---|---|
| 核心层 | `core/` | **入库** | 能独立复现核心能力 |
| 设备参考层 | `device-ref/` | **入库** | 参考实现，固件骨架与模型包格式 |
| 交付层 | `deploy/` | **不入库** | 只在本司内网成立的适配 |

判据是**可复现性**，不是"开源/私有"（见 [ADR-002](../docs/adr/README.md)）。
如果你加的东西只有在内网才能跑通，它属于 `deploy/`。

---

## 二、开发环境

| 组件 | 版本 | 说明 |
|---|---|---|
| JDK | 21 | 用 17 会编译失败（class file 61.0 vs 65.0） |
| Maven | 3.9 | 本地仓库路径按你的机器调整 |
| Python | 3.13 | 3.10 装不上 `chromadb==1.5.9` |
| ChromaDB | 1.5.9 | 由 `core/scripts/chroma.ps1` 管理，监听 `127.0.0.1:8765` |

```powershell
# Python 依赖
python -m pip install -r core\requirements.txt
```

**仓库内不出现任何真实凭据。** 密钥一律走环境变量注入（清单见
[`core/README.md`](../core/README.md#环境变量)）。带凭据的提交会被门禁打回。

---

## 三、提交前的自检清单

**每一项都要真跑过，不要只读代码确认。**

```powershell
# 1. 端侧（Python）—— 应为 518 项全过、0 失败
python -m pytest core\tests -v

# 2. 云端（Java）—— 应为 357 项全过、0 失败、BUILD SUCCESS
cd core\cloud
$env:JAVA_HOME = '<你的 JDK 21 路径>'
mvn test

# 3. 协议一致性（两侧判定必须相同）
powershell -ExecutionPolicy Bypass -File core\scripts\validate-protocol.ps1

# 4. 端到端门禁（需要服务在跑）
powershell -ExecutionPolicy Bypass -File core\scripts\e2e.ps1

# 5. 评测门禁（六个维度）
powershell -ExecutionPolicy Bypass -File core\scripts\eval.ps1
```

第 3 项尤其重要：**协议 schema 只有一份，但校验器有两份实现**
（Python 与 Java）。任何 schema 改动都必须让两侧判定一致，
否则真机上会出现"端侧认为合法、云端认为非法"的静默丢包。

---

## 四、改动规约

### 4.1 命名与常量

| 禁止 | 要求 | 反例 → 正例 |
|---|---|---|
| 拼音命名、拼音英文混排 | 完整英文单词组合 | `DaZhePromotion` → `DiscountPromotion` |
| Boolean 加 `is` 前缀 | 直接用语义词 | `isDeleted` → `deleted` |
| 魔法值散落在业务代码 | `static final` 常量或枚举 | `if (type == 3)` → `IntentType.X` |
| 下划线/美元符号开头结尾 | 常规驼峰 | `_name`、`$total` |
| `Executors.newFixedThreadPool` | 显式 `ThreadPoolExecutor` 并指定队列容量 | |

### 4.2 分层依赖单向

```
端侧 Python：simulator → transport → session → dialog / intent → audio
云端 Java ：web → session → memory / reply → protocol
```

- 端侧与云端**不共享代码，只共享协议** —— 跨语言反而逼着协议设计更严谨
  （[ADR-003](../docs/adr/README.md)）。
- 云端 Entity **不得直接暴露给 Controller**，必须经 DTO。
- Repository 不得依赖 Service。

### 4.3 注释写"为什么"，不写"是什么"

```java
// 差：递增序号
sequence++;

// 好：序号从 0 起且连续 —— 固件按"序号跳变"判丢包，
// 从 1 起会让固件把第一帧误判为丢包。
sequence++;
```

### 4.4 架构决策要留档

如果你做了一个**有取舍**的技术选择（不是"显然就该这么写"），
在 [`docs/adr/README.md`](../docs/adr/README.md) 里加一条 ADR，格式固定：

```
背景 / 选项 / 选定 / 理由 / 未选其他选项的原因 / 代价 / 什么情况下应该重新评估
```

最后一段**刻意保留** —— ADR 不是墓碑，是决策的依据。
写清"什么条件下这个决策就不成立"，比写清"当初为什么这么选"更有用。

### 4.5 新增公共能力要带测试

新增公共方法或类，必须同时补单元测试骨架，至少包含：

- **happy path** —— 正常输入产出预期结果
- **一条失败路径** —— 异常输入下行为符合约定（抛错或降级，**不许静默吞掉**）

---

## 五、评测门禁的约束

改动如果碰到意图判定、记忆召回、记忆作答、安全策略、共情判定，
请注意门禁阈值**全部集中在单一模块**
（云端 `EvalGates.java` 的 `MIN_*` / `MAX_*` 常量）。
**不要在脚本或测试里另写一份阈值** —— 那正是历史上出过错的地方。

| 维度 | 阈值 | 口径 |
|---|---|---|
| `intent_accuracy` | ≥ 0.85 | 意图分类准确率 |
| `memory_recall_at_k` | ≥ 0.90 | 长期记忆召回命中率 |
| `memory_answer_accuracy` | ≥ 0.95 | 作答准确率（拒答不进分子也不进分母） |
| `memory_answer_rate` | ≥ 0.75 | 作答率（防止"永远拒答"也拿满分） |
| `memory_fabrication_rate` | ≤ 0.05 | 编造率（本维度最不能妥协的一项） |
| `safety_recall` | ≥ 0.95 | 安全策略召回率 |
| `empathy_rate` | ≥ 0.75 | 情感标签判定正确率 |
| ASR clean | ≥ 0.80 | 端侧识别准确率 |

**尤其注意**：改动记忆相关逻辑时，作答率 76.9% 相对 75% 阈值只有
1.9 个百分点的余量。任何让"问题与记忆表述的词面重叠度"下降的改动，
都可能把它推到阈值之下 —— 这时要改的是**能力**，不是阈值。

---

## 六、提交信息规范

用 Conventional Commits，标题行控制在 72 字符内：

```
<type>(<scope>): <subject>

<body>

<footer>
```

**type 取值**：`feat` / `fix` / `docs` / `test` / `refactor` / `perf` /
`chore` / `build` / `ci`。

**scope 用模块名**：`edge` / `cloud` / `protocol` / `eval` / `e2e` / `docs` / `device-ref`。

示例：

```
fix(eval): e2e.ps1 跳过服务启动时先探活后端，避免把缺服务误报成断言失败

-SkipServices 分支原先假定依赖已在运行，未验证 :8080/api/health。
后端停掉时，断言失败与"环境没起"混在一起，退出码语义不清。

新增健康探针：不可达时以退出码 2（ExitEnvUnavailable）快速失败。
```

---

## 七、Pull Request

**标题**用 Conventional Commits 格式，与提交信息一致。

**正文**请覆盖这几节：

1. **改了什么** —— 一句话。
2. **为什么** —— 关联的 issue / ADR / 已知限制条目。
3. **怎么验证的** —— 贴出实际命令与**实测数字**。
   不要写"测试通过"这种没有数字的话。
4. **影响面** —— 改了哪些接口 / 类，是否破坏向后兼容，调用方要不要跟着改。
5. **已知限制是否变化** —— 若涉及能力边界，同步更新 `docs/known-limitations.md`。

**PR 里不要出现**：模型权重、真人录音、任何真实凭据、内网地址、
生成物（`core/eval-report.*`、`data/reports/`）。这些已被 `.gitignore` 排除，
提交前请确认 `git status` 干净。

---

## 八、行为准则与安全问题

- 参与讨论请遵守 [`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md)。
- 发现安全问题请按 [`SECURITY.md`](SECURITY.md) 私下报告，**不要**开公开 issue。

---

## 九、需要帮助时

- 第一次上手：[`docs/operations-manual.md`](../docs/operations-manual.md)
- 部署：[`docs/deployment.md`](../docs/deployment.md)
- 二次开发：[`docs/secondary-development.md`](../docs/secondary-development.md)
- 已知限制：[`docs/known-limitations.md`](../docs/known-limitations.md)
- 架构评审：[`docs/architecture/README.md`](../docs/architecture/README.md)
