# 推送到 GitHub 的操作指引

本文件记录**把本仓库发布到 GitHub 的完整步骤**，
包括 GitHub 上必须勾选的设置项 —— 这些设置**不在代码里**，
漏掉任何一项，仓库在 GitHub 上的呈现就会缺一块。

> 当前状态：本地已全部提交，工作区干净（`git status` 无输出），
> 共 59 个提交、379 个入库文件。
> **尚未配置远程仓库**（`git remote -v` 为空），需要按本文第 2 节操作。

---

## 1. 发布前的自检（已全部实测通过）

| 检查项 | 命令 | 实测结果 |
|---|---|---|
| 端侧测试 | `python -m pytest core\tests` | **518 项全过**，0 失败，13 跳过 |
| 云端测试 | `cd core\cloud && mvn test` | **357 项全过**，0 失败，19 跳过，BUILD SUCCESS |
| 协议一致性 | `core\scripts\validate-protocol.ps1` | **28 条样例全过** |
| 端到端门禁 | `core\scripts\e2e.ps1` | **8/8 断言全过** |
| 评测门禁 | `core\scripts\eval.ps1` | **五维 + 次级门禁全过** |
| 部署反证 | `core\deploy-test\verify_deploy_tests_catch.py` | 三处破坏均被咬住，恢复后全绿 |
| 凭据扫描 | 全仓 `sk-*` / `ghp_*` / `AKIA*` 模式 | **无命中** |

---

## 2. 创建 GitHub 仓库并推送

### 2.1 在 GitHub 上建仓（网页）

1. 打开 <https://github.com/new>。
2. **Repository name**：`voice-companion`
   （或你的偏好名）。
3. **Public / Private**：作品集场景选 **Public**。
4. ⚠️ **不要勾选**以下四项 —— 本地已有完整历史，勾了会冲突：
   - ❌ Add a README file
   - ❌ Add `.gitignore`
   - ❌ Choose a license
   - ❌ Create a new branch
5. 点 **Create repository**。

### 2.2 关联并推送（本地）

```powershell
cd D:\myproject\voice-companion

# 关联远程（把 <你的账号> 换成实际用户名）
git remote add origin https://github.com/<你的账号>/voice-companion.git

# 确认远程已生效
git remote -v

# 推送
git push -u origin feature/phase1-protocol-simulator
```

推送时 GitHub 会要求认证，三选一：

| 方式 | 说明 |
|---|---|
| **Personal Access Token**（推荐） | <https://github.com/settings/tokens> 生成，勾 `repo` 权限；用 Token 代替密码 |
| HTTPS + 交互式登录 | 输入账号 + Token，**密码认证已于 2021 年停用** |
| SSH | `git remote set-url origin git@github.com:<你的账号>/voice-companion.git` |

### 2.3 默认分支

**本仓库已把分支改名为 `main`**（原来的 `feature/phase1-protocol-simulator`），
全部 60 个提交都在这一条分支上。推送时直接推 `main`：

```powershell
git push -u origin main
```

推送后到 GitHub 网页确认 **Settings** → **Branches** →
右侧 **Default branch** 显示为 `main`（新建仓库时默认就是它，一般无需改）。

> 改名之前的分支名若已被别人 clone 过，对方需要
> `git branch -m main && git push -u origin main`，
> 或 `git remote set-head origin -a` 切过去。

---

## 3. GitHub 仓库设置（**必须逐项确认**）

代码推上去只是第一步。下面这些设置**只存在于 GitHub 网页上**，
不设置的话，评审者看到的仓库是不完整的。

### 3.1 About（仓库简介）

**Settings** → **General** → 右侧 **About**：

| 字段 | 填什么 |
|---|---|
| Description | `端云全链路的语音情感陪伴机器人：协议契约、记忆能力、评测门禁。MIT 许可。` |
| Website | 留空或填你的个人主页 |
| Topics | `voice-assistant`、`speech-recognition`、`memory`、`chroma`、`spring-boot`、`faster-whisper`、`json-schema`、`evaluation-gate` |

> Topics **直接影响仓库的可发现性** —— 搜"语音助手"能搜到它。

### 3.2 README 渲染

仓库首页会渲染 `README.md`。确认这几项生效：

- 顶部徽章区（可选，见 §3.6）。
- "实测指标"表格正常显示。
- "十分钟跑通"的代码块有语法高亮。
- 所有相对链接可点开（`docs/...` 路径大小写**完全正确** ——
  Linux 上大小写敏感，Windows 上不敏感，本地能过而 GitHub 上 404 的
  最常见原因就是这个）。

### 3.3 Issues（问题追踪）

**Settings** → **General** → **Features** → **Issues** → 勾选 **Enable**。

**issue 模板已内置**（`.github/ISSUE_TEMPLATE/`）：缺陷报告 + 功能请求。

缺陷报告模板里有一栏值得特别说明：

> **是否触及已知限制** —— 这一栏能挡住"这个功能怎么不支持"的重复提问。
> 先查 `docs/known-limitations.md`，若已记录过就勾选并注明条目编号，
> 省掉一轮重复排查。

### 3.4 Pull Requests

**Settings** → **General** → **Features** → **Pull Requests** → 勾选 **Enable**。

**PR 模板已内置**（`.github/PULL_REQUEST_TEMPLATE.md`），内容与
`CONTRIBUTING.md` §7 一致：改了什么 / 为什么 / **怎么验证的（附实测数字）**
/ 影响面 / 已知限制是否变化。

模板里"怎么验证的"一栏明确要求**贴实测数字**，
不接受"测试通过"这种没有数字的话。

### 3.5 Discussions（讨论区）

**Settings** → **General** → **Features** → **Discussions** → 勾选 **Enable**。

这个项目讨论的往往是**取舍**（阈值该不该调、能力边界算不算已实现），
用 issue 讨论这类问题会很乱。开了 Discussions 之后，
把 README 里"哪些支持、哪些不支持"的链接指过去。

### 3.6 安全与分支保护（如果公开维护）

**Settings** → **Code security and analysis**：

| 项 | 建议 |
|---|---|
| Code scanning | 启用（GitHub CodeQL 对 Java / Python 都支持） |
| Dependabot alerts | 启用 |
| Dependabot security updates | 启用 |
| Secret scanning | 启用（**公开仓库默认开启**，本仓库已确认无凭据命中） |

**Settings** → **Branches** → **Add rule**（保护 `main`）：

- Require a pull request before merging
- Require status checks to pass（跑 CI 后再启用，见 §4）

### 3.7 Actions（CI）

**Settings** → **Actions** → **General** → 勾选
**"Allow all actions and reusable workflows"**（或按需限定）。

---

## 4. CI 工作流（**已内置**，见 `.github/workflows/ci.yml`）

仓库里**已经放好**一份可用的 CI 工作流，推上去即生效。它跑四个 job：

| job | 检查 | 依赖 |
|---|---|---|
| `edge` | 端侧测试（Python） | 仅 pytest / jsonschema / websockets / numpy |
| `cloud` | 云端测试（Java） | JDK 21 + Maven |
| `protocol` | 协议一致性（两侧判定必须相同） | pwsh + jsonschema |
| `docs` | 交付文档一致性 | 同 edge |

> **为什么 `eval.ps1` / `e2e.ps1` 不在 CI 里**：
> 它们需要 ChromaDB + 本地嵌入服务 + 可选的大模型凭据，
> 而模型权重按 ADR-006 不入库（由 `core/scripts/fetch-models.ps1` 下载）。
> 与其跑一个经常因为环境问题变红的门禁，不如让这四项守住真正能守的部分。
>
> **端侧测试在 CI 上会有跳过项** —— 依赖本地服务的用例跳过，
> 本地实测是 518 项里 13 项跳过。**关心的是 0 失败，不是 518 全过。**

**唯一需要手动开的设置**：

**Settings** → **Actions** → **General** → 勾选
**"Allow all actions and reusable workflows"**（或按需限定）。

若要启用**分支保护**，先让 CI 跑一次拿到 check 名称，再在
**Settings** → **Branches** → **Add rule** 里勾
*Require status checks to pass*。

### 4.1 为此做的两处可移植性修复

CI runner 是 Linux，因此顺手修掉两处会在 CI 上直接失败的问题：

1. `validate-protocol.ps1` 里写死的 `F:\tools\python313\python.exe`
   → 改为**环境变量 → PATH → 默认值**三级回退解析；
2. 该脚本里的 `protocol\schema` 反斜杠路径
   → 改为 `protocol/schema`，PowerShell 在 Windows 与 Linux 上都认。

本机复验：28 条样例仍全过；`core/tests/scripts` 15 项全过（含 BOM 断言）。

---

## 5. 发布首个 Release（可选）

仓库首次公开后建议打一个 tag：

```powershell
git tag -a v0.1.0 -m "第一阶段收口：端云双向链路 + 记忆能力 + 评测门禁"
git push origin v0.1.0
```

然后在 GitHub → **Releases** → **Draft a new release** → 选择 tag → 发布。

**Release 说明直接用 `CHANGELOG.md` 的 v0.1.0 条目** ——
它已经按"每项都附验证方式"写好了。

---

## 6. 推送后的复核清单

推完不是结束。**在 GitHub 网页上**逐项确认：

- [ ] 首页 README 正常渲染，表格与代码块无异常
- [ ] 所有 `docs/...` 相对链接可点开（**大小写完全正确**）
- [ ] `LICENSE` 被 GitHub 识别为 MIT（仓库右侧显示 "MIT license"）
- [ ] `SECURITY.md` / `CODE_OF_CONDUCT.md` / `CONTRIBUTING.md`
      在仓库首页的链接区可见（GitHub 会自动识别这三个文件）
- [ ] `About` 的描述与 Topics 已填
- [ ] Issues / Pull Requests / Discussions 已启用
- [ ] 浏览器直接访问 `https://raw.githubusercontent.com/<账号>/voice-companion/main/README.md`
      能取到内容（确认 `.gitignore` 没有误伤源文件）
- [ ] `core/eval-report.md` **不应**出现在仓库里 —— 它是运行产物，
      被 `.gitignore` 排除；出现了说明忽略规则被改坏了

---

## 7. 已知会被 GitHub 拒绝或需要注意的项

| 项 | 说明 |
|---|---|
| `docs/architecture/*.docx` | 被 `.gitignore` 排除（1.1 MB 生成物）。**这是有意的** —— 源文件在 `docs/architecture/parts/`，用 `tools/build_companion_doc.py` 重新生成 |
| `core/eval-report.*` | 运行产物，不入库。评审者要看指标请跑 `core\scripts\eval.ps1` |
| `data/reports/` | 同上 |
| 真人录音 | 被 `.gitignore` 排除，且属于特定人员的生物特征数据，**不要**提交 |
| 模型权重 | 被 `.gitignore` 排除，用 `core\scripts\fetch-models.ps1` 下载 |
| `deploy/` | 公司私有层，不入库（见 ADR-002） |

> 这些"看不到的东西"在 README 与 `docs/known-limitations.md` 里都有说明，
> 评审者能查到它们是什么、怎么生成。

---

## 8. 推送前的最后确认

```powershell
cd D:\myproject\voice-companion

# 工作区必须干净
git status              # 期望：无输出

# 确认没有凭据
git ls-files | Select-String -Pattern '\.env$|\.pem$|id_rsa'

# 确认将要推送的提交
git log --oneline -5

# 确认远程
git remote -v
```
