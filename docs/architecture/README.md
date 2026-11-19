# 架构方案文档

本目录是《语音情感陪伴机器人 技术架构方案 V1.0》的**源文件**。

## 目录结构

```
docs/architecture/
├── parts/                                    ← 源文件（手工维护）
│   ├── part00_cover.md                       封面
│   ├── part01_overview.md                    第 1 章 目标、范围与总体架构
│   ├── part02_edge_hardware.md               第 2 章 端侧硬件
│   ├── part03_edge_ai.md                     第 3 章 端侧 AI
│   ├── part04_model_deploy.md                第 4 章 模型部署
│   ├── part05_cloud.md                       第 5 章 云端服务
│   ├── part06_tts.md                         第 6 章 TTS 与音色
│   ├── part07_memory.md                      第 7 章 记忆（§7.6 记忆质量门禁）
│   ├── part08_persona.md                     第 8 章 人设与对话体验
│   ├── part09_performance.md                 第 9 章 时延与成本
│   ├── part10_security.md                    第 10 章 安全合规
│   ├── part11_roadmap.md                     第 11 章 里程碑
│   ├── part12_challenges.md                  第 12 章 挑战与优化（含 §12.5 先验清单）
│   └── part13_appendix.md                    附录 A–E
├── assets/                                   ← 架构图（由脚本生成）
│   ├── 端云协同总体架构图.png
│   ├── 端侧模型训练部署流水线.png
│   ├── 记忆与千人千面架构图.png
│   └── 实时语音会话时序图.png
└── 语音情感陪伴机器人_技术架构方案_V1.0.md   ← **生成产物**，勿手改
```

## 改内容请改 `parts/`，不要改合并产物

合并产物 `语音情感陪伴机器人_技术架构方案_V1.0.md` 由
`tools/build_companion_doc.py` 从 `parts/*.md` 拼接生成。
**直接改产物会在下次构建时被静默覆盖** —— 改动看起来生效了，实则会丢失。

构建脚本已内置一致性校验：产物与源文件不一致时会报警并以退出码 1 结束。

## 构建

```powershell
# 1. 重建架构图（改了 parts/part02~part04、part07、part09 的图示后需要）
F:\tools\python313\python.exe tools\build_companion_diagrams.py

# 2. 合并 parts/ → markdown → docx
F:\tools\python313\python.exe tools\build_companion_doc.py

# 3. 校验产物与源文件是否一致（日常巡检）
F:\tools\python313\python.exe tools\sync_parts_from_product.py --check
```

产物 `docx` 与 `zip` 打包件不���库（见 `.gitignore`），需要时重新生成。

## 已发生过的漂移（留档以说明这道防线为什么必要）

§1.1.1「已实测值」、§7.6.1–§7.6.3 这几节一度**只存在于合并产物**，
`parts/` 源文件并未同步 —— 任何人跑一次构建脚本，这些内容就会全部消失。

已通过 `tools/sync_parts_from_product.py` 回填修复，并加上了构建期校验。
**这个坑不会再踩第二次。**

## 与仓库其他文档的关系

本目录是**架构方案**（对外评审用，11 章 + 5 附录）。
工程执行类文档在上一级：

| 文档 | 位置 | 内容 |
|---|---|---|
| 部署手册 | `docs/deployment.md` | 环境变量、端口、排查路径 |
| 已知限制 | `docs/known-limitations.md` | 每条限制的验证方式与实际状态 |
| 二次开发指南 | `docs/secondary-development.md` | 协议只改一处等三条不变量 |
| ADR | `docs/adr/README.md` | 架构决策记录 |
| 接口契约 | `docs/interface-contract/README.md` | 跨语言一致性约束 |
