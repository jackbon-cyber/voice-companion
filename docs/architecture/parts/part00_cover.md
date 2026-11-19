# 语音情感陪伴机器人 技术架构方案

| 项 | 内容 |
|---|---|
| 文档名称 | 语音情感陪伴机器人（Voice Emotional Companion）端云协同技术架构方案 |
| 版本 | V1.0 |
| 状态 | 架构评审稿 |
| 适用对象 | 端侧固件、云端服务、算法、算法工程、测试、运维 |
| 技术基线 | STM32N6 / Ethos-U55 NPU · whisper.cpp · Silero VAD · Qwen2.5-0.5B LoRA · Qwen2.5-Omni-TTS · AgentScope 2.0.4（Java）· Chroma + pgvector · Spring Boot 3.3.5 · K8s |
| 关联资产 | `voice-companion/docs/architecture/assets/` 四张架构图；仓库既有 `openspec/changes/add-agentscope-chroma-memory-kb` 记忆库设计与 `docs/agent-platform/` 17 层方案 |

---

## 0. 阅读指引

| 读者 | 建议阅读路径 |
|---|---|
| 决策者 | 第 1 章 → 第 2.1 节（总体拓扑）→ 第 11 章（里程碑与风险） |
| 端侧固件负责人 | 第 3 章 → 第 4 章 → 附录 A（目录结构）、附录 D（OTA 脚本） |
| 云端负责人 | 第 5 章 → 第 6 章 → 第 7 章 → 附录 B（接口契约）、附录 C（数据模型） |
| 算法负责人 | 第 4.2–4.5 节 → 第 8 章（音色克隆） |
| 测试负责人 | 第 9 章（性能预算）→ 第 10 章（验收门禁）→ 附录 E（评测集规范） |

本方案中所有性能数字为**设计目标值**，不是实测值；实测门槛定义在第 10 章，达标后方可进入量产。
