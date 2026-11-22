# device-ref —— 设备侧参考实现

> STM32 固件骨架与模型包打包工具。**这是参考实现，不是量产固件。**
> 与真机的差异见本文档末尾的"未验证项"。

## 目录

| 路径 | 内容 |
|---|---|
| `firmware/include/` | 固件接口定义：协议常量、采集与 VAD、ASR、意图判定、状态机。 |
| `model-package/` | 模型包格式定义（`manifest.json` + 模型文件 + 签名）与打包脚本。 |
| `ota/` | OTA 脚本骨架：A/B 分区、断点续传、验签、自检回滚。 |

## 固件任务划分

固件被切成四个任务，每个任务一个头文件。切分依据是**谁在等谁**：
音频任务永远在跑，其余任务等音频任务喂数据；云端消息任务独立于语音链路，
即使识别卡住也要能接收降级指令。

| 任务 | 头文件 | 职责 | 等待关系 |
|---|---|---|---|
| 采集与 VAD | `vc_audio_task.h` | I2S/DMA 采集 → 帧组装 → VAD 判定 → 20ms 定长帧输出 | 永不等待 |
| 端侧 ASR | `vc_asr_task.h` | 接收断句后的语音段 → 调用识别后端 → 产出文本与置信度 | 等语音段 |
| 意图判定 | `vc_intent_task.h` | 规则表判定意图 → 决定本地处理还是上云 | 等识别文本 |
| 会话状态机 | `vc_state_machine.h` | 六态流转、打断处理、状态超时回退 | 被所有任务驱动 |

关键约束：

- **帧长固定 20ms（320 采样点）**。变长帧会让云端分片重组与端侧帧序号对不上，
  表现为"偶发丢字"，且只在语音长短不一时出现。
- **状态机六态必须与端侧 Python 实现一致**
  （`core.edge.session.state_machine.SessionState`）。
  两端状态集不一致时，固件会停在 Python 侧不存在的状态上。
- **打断只丢"还没播出去的音频"，不丢"已识别的文本"。**
  用户打断说"等等"，机器人应把已识别的那句接着说完，而不是当作没发生过。

以上三条由 `core/tests/device_ref/test_firmware_interfaces.py` 守着。

## 与云端的关系

设备侧只跑**端侧职责**：音频采集、VAD、端侧 ASR、意图判定、本地兜底对话、
降级判定。协议消息的定义在 `core/protocol/schema/`，
**设备侧与 PC 模拟端共用同一份协议** —— 换设备不改协议。

固件不解析 JSON（flash 占用与实时性都不允许），
但 `vc_protocol.h` 把每个字段名固化成常量，值取 schema 里的原始字段名。
schema 改字段名而固件没改，测试立刻失败。

## 与 PC 模拟端的关系

| 维度 | PC 模拟端（`core/edge/`） | 设备侧（`device-ref/`） |
|---|---|---|
| 语言 | Python | C |
| 音频输入 | 麦克风 / 模拟源 | I2S / DMA 采集 |
| ASR | faster-whisper | 厂商 SDK 或量化小模型 |
| 意图 | 规则表 + 小模型 | 规则表（模型在 flash 里不划算） |
| 对话 | llama.cpp / 话术库 | 话术库 |
| 用途 | 功能验证、协议验证、指标基线 | 硬件集成验证 |

**PC 模拟端是设备侧的行为参考**：协议语义、降级策略、打打断处理在两侧必须一致。

## 模型包

打包脚本：`device-ref/model-package/package_model.py`。

```powershell
# 生成签名密钥（只需一次；私钥不得入库）
F:\tools\python313\python.exe device-ref/model-package/package_model.py --gen-key keys/device_sign_key.pem

# 打包
F:\tools\python313\python.exe device-ref/model-package/package_model.py --manifest build/manifest.json --out dist/companion_model_pkg --sign-key keys/device_sign_key.pem
```

产物是**目录**而非单一容器文件（原因见 `model-package/README.md` 的
"与技术架构方案 §4.6 的偏离"一节）。未提供签名密钥时脚本直接失败 ——
未签名的模型包等于明文分发模型文件，攻击者可替换模型而设备端无从察觉。

## OTA

脚本：`device-ref/ota/ota_update.py`。

```powershell
# 只演练流程，不碰设备
F:\tools\python313\python.exe device-ref/ota/ota_update.py --image dist/firmware-2.5.0.bin --device COM3 --dry-run

# 自检
F:\tools\python313\python.exe device-ref/ota/ota_update.py --self-check
```

三条不可协商的规则：

1. **验签失败即中止** —— 刷入未经验签的镜像等于放弃全部安全保证。
2. **只写备用分区** —— 当前运行分区永远不动，它是唯一可回退的保障。
3. **自检通过才切换** —— 自检不过就留在旧分区继续跑。

`--dry-run` **不打开设备、不写串口、不下发任何命令**，只演练流程编排与参数判定。

## 行为契约：什么能在 PC 上验，什么必须等真机

固件（`device-ref/firmware/include/*.h`）与 PC 模拟端（`core/edge/`）
是同一套端侧行为的两份实现。**结构一致不等于行为一致** ——
固件头文件里写着的语义承诺，和 PC 侧实际跑出来的行为可能对不上，
而这类分歧**编译通过、联调通过、直到真机跑起来才暴露**。

因此把行为契约写成机器可检查的形式：

| 文件 | 作用 |
|---|---|
| `core/edge/device_ref/behavior_contract.py` | 契约清单：每条声明"固件侧语义"与"PC 侧参考实现"，并写明"不做会怎样" |
| `core/tests/device_ref/test_behavior_contract.py` | 逐条核对：数值常量取值一致、枚举集合相同、行为规则**实际执行验证** |
| `core/tests/device_ref/test_firmware_interfaces.py` | 原有结构契约（字段名、状态集合、协议常量） |

**行为规则要真的跑一遍**，不能只比对符号名。
例如"打断丢音频、留文本" —— 两边都有 `on_recognized` 函数，
但 PC 侧若只记长度不记内容，打断时文本就没了。**只有真的打断一次才知道**。

### 已在契约核对中查出并修复的分歧

| 分歧 | 固件侧 | PC 侧 | 后果 |
|---|---|---|---|
| 意图降级阈值 | `VC_INTENT_KEYWORD_ONLY_THRESHOLD 400`（0.4） | `RECOGNITION_CONFIDENCE_THRESHOLD 0.5` | 同一句话在固件上按关键词执行、在模拟端却拒识 |
| 打断事件缺文本长度 | `retained_text_length`（uint16） | 只有 `retained_text`，无长度 | 固件实现者只能猜该填什么；填 0 等于"文本全丢了" |

后者的修法是给 PC 侧 `BargeInEvent` 补 `retained_text_length` 属性
（UTF-8 字节数，与固件 `uint16` 口径一致）。

### 必须在真机上测的项

以下**不能**在 PC 侧断言，列在 `HARDWARE_ONLY_MEASUREMENTS` 里并写明验证方式：
打断响应延迟绝对值、端侧 ASR 在 Cortex-M 上的延迟、任务栈与队列深度、
I2S/DMA 中断抖动与时钟漂移、flash 余量、功耗与温升、OTA 真实切换与回滚。

**这份清单的价值在"排除"**：把"PC 上验不了的"明确列出来，
避免有人在 PC 上给它们编一个假的通过结论。

## 未验证项

> 以下内容在参考实现中**未经过真机验证**，不得当作已验证能力对外承诺。

- [ ] **音频采集**：I2S / DMA 时序、中断延迟、时钟漂移未在真机测量。
      参考实现只保证"能收到 20ms 一帧的 PCM"。验证方式：在目标板上测中断抖动与丢帧率。
- [ ] **端侧 ASR**：未在 STM32 上跑通量化模型。参考实现假定由厂商 SDK 提供识别能力。
      验证方式：在目标板上跑通一段真实录音，确认延迟与内存占用达标。
- [ ] **端侧对话**：flash 容量与算力是否够跑小模型**未评估**。
      设备侧按"只有话术库"设计。验证方式：量测 flash 余量与响应延迟。
- [ ] **固件任务划分**：四个任务的优先级、栈大小、消息队列深度**未在真机调优**。
      验证方式：在目标板上跑压力场景，确认无优先级反转与栈溢出。
- [ ] **OTA**：A/B 分区切换、验签、失败回滚的**真机流程未走通**。
      脚本支持 `--dry-run`，只验证参数与流程编排，不碰真实设备。
      验证方式：真机执行一次完整升级，并人为制造断电与验签失败各一次。
- [ ] **模型包安装**：设备端的包安装与校验流程**未实现**，只有打包侧。
      验证方式：设备端实现安装器后做一次端到端安装。
- [ ] **功耗与温升**：无任何实测数据。验证方式：目标板功耗仪实测典型与峰值工况。
- [ ] **EMC / 射频合规**：不在本仓库范围内。验证方式：由认证机构另行出具报告。
- [ ] **量产相关的供应链、产测、售后**：不在本仓库范围内。
      验证方式：由产线与售后体系各自承接。

## 使用约定

`device-ref/` 是**参考实现**，改动前先确认：

1. 改动是否涉及协议语义？→ 先改 `core/protocol/schema/`，两侧同步。
2. 改动是否影响 PC 模拟端行为一致性？→ 同步改 `core/edge/` 并跑测试。
3. 改动是否只是硬件适配？→ 留在本目录，不进 `core/`。
