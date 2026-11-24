# 部署实测（第四步）

按 `docs/operations-manual.md` 第 4 章在**真实 Linux 容器**里跑一遍部署，
并逐项验证手册承诺的行为。

> 这不是交付物，是**验证工具**。它的价值在于把"手册读起来对"
> 和"实际部署真的能跑"分开。

## 复现步骤

前置：Docker（本机实测版本 29.5.2）。

```powershell
# 1. 准备产物（jar 由 Maven 构建，模型与 Python 包从仓库拷过去）
cd voice-companion\core\deploy-test
New-Item -ItemType Directory -Force -Path app\models | Out-Null
Copy-Item ..\..\core\cloud\target\voice-cloud-0.0.1-SNAPSHOT.jar app\voice-cloud.jar -Force
Copy-Item ..\..\core\models\embedding app\models\embedding -Recurse -Force
New-Item -ItemType Directory -Force -Path app\core\edge\embedding | Out-Null
Copy-Item ..\..\core\__init__.py app\core\__init__.py -Force
Copy-Item ..\..\core\edge\__init__.py app\core\edge\__init__.py -Force
Copy-Item ..\..\core\edge\embedding\service.py app\core\edge\embedding\service.py -Force
Copy-Item ..\..\core\edge\embedding\__init__.py app\core\edge\__init__.py -Force

# 2. 构建镜像
docker build -t voice-companion-deploy:test .

# 3. 起服务
docker run -d --name vc-deploy -p 18080:8080 -p 18765:8765 -p 18766:8766 voice-companion-deploy:test
```

## 探针脚本

| 脚本 | 验什么 | 怎么跑 |
|---|---|---|
| `probe_auth.py` | 上行通道鉴权：无凭据 / 错凭据 / 对凭据 | 宿主机的 `python313` 跑 |
| `probe_conversation.py` | 完整对话链路：记忆写入 → 召回 → 引用 | 同上 |
| `probe_isolation.py` | 跨用户隔离 + 跨会话隔离 | 同上 |
| `probe_chroma.py` | 直查 Chroma：存了什么、查不查得到、作用域过滤 | `docker cp` 进容器跑 |
| `probe_similarity.py` | 召不回时定位原因：阈值 vs 检索 | `docker cp` 进容器跑 |
| `probe_failfast.sh` | schema 缺失时启动必须失败 | `docker cp` 进容器跑 |
| `verify_deploy_tests_catch.py` | **反证**：确认新增的部署回归测试真的会失败 | 宿主机的 `python313` 跑 |

### `verify_deploy_tests_catch.py` 是干什么的

新增的 3 条部署回归测试钉的是**文档与 pom 配置**，
而文档漂移恰恰是"改了没人发现"的典型。

**钉子钉歪了比不钉更糟** —— 它会给出虚假的安心感。
所以这个脚本故意破坏三处内容，确认对应的测试会**红**：

1. 去掉 `pom.xml` 的 `<resources>` 声明 → schema 不进 jar；
2. 从启动顺序里删掉嵌入服务；
3. 把 Python 版本要求改成 3.8。

三处都必须让对应测试失败（而不是绿着放行），恢复后必须重新变绿。

> ★ 这条反证**当场抓到了我自己写的测试的缺陷**：
> 第三条最初只判 `"3.13" in text`，但文件别处也会出现 3.13 ——
> 把要求改成 3.8 竟然还能通过。已改成判"要求行"。
> **没有这道反证，这条测试会一直绿着，而它其实什么也没钉住。**


宿主机的探针脚本需要 `websockets`：

```powershell
$env:PYTHONPATH="D:\myproject\voice-companion"
F:\tools\python313\python.exe probe_auth.py
```

容器内的探针要把端口改成容器内地址（`127.0.0.1:8766`，不是 `18766`）。

## 这次实测发现并修掉的问题

1. **协议 schema 没进 jar** —— 部署后协议校验完全失效且静默降级；
2. **手册没说明目标机要 Python 3.13** —— ChromaDB 1.0 在 Python 3.8 上装不上；
3. **ChromaDB 1.0 需要 C++ 编译器** —— 缺时报错极具误导性；
4. **手册的启动顺序与 systemd 单元漏了嵌入服务**。

详见 `docs/operations-manual.md` 4.8.3。

## 环境相关的坑（本机网络状况）

| 目标 | 结果 |
|---|---|
| Maven Central | ✗ 不可达 |
| 阿里云 Maven 镜像 | ✓ 可达 |
| Docker Hub | ✗ 部分 CDN 域名解析失败 |
| 华为云 openjdk 镜像 | ✓ 可达（JDK 21 从这拉） |
| Adoptium 官方 API | API 可达，但 307 重定向到 GitHub —— **不可达** |
| GitHub | ✗ 不可达 |
| PyPI | ✓ 可达 |

**换网络环境时 `Dockerfile` 里的 `JDK_URL` 可能要改**，
改前先验证 tar 能解开、`java -version` 能跑。
