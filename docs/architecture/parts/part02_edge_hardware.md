# 2. 端侧硬件与固件架构

## 2.1 硬件选型与双档产品线

| 档位 | SoC | AI 加速 | 内存 | 存储 | 定位 | 零售价带目标 |
|---|---|---|---|---|---|---|
| MCU 档 | STM32N6（Arm Cortex-M55 + Ethos-U55 NPU 128 MACs） | NPU 128 MACs | 2.5MB SRAM + 4MB TCM | 32MB SPI NOR + 16MB eMMC | 轻陪伴、桌面摆件、闹钟/天气/陪伴短聊 **（不含端侧 ASR，见 P0-1）** | ¥299–499 |
| MPU 档 | STM32MPU257（双 Cortex-A7 + NPU Ethos-U85） | NPU | DDR 512MB/1GB | NOR 64MB + eMMC 32GB | 全功能陪伴（本地 LLM + 端侧 TTS + 视觉扩展位） | ¥899–1299 |

**共用外设**：MEMS 麦克风阵列（3 麦 + 环形）、Class-D 功放 + 4Ω 8W 喇叭、1.54" MIPI 彩屏（表情）、RGB 灯环（情绪）、触摸/按键（打断）、电池 + 充电。

**为什么以 STM32N6 为 MCU 档底座**：内置 Ethos-U55 NPU（INT8）与 ST Edge AI Core 工具链，官方提供 N6 系列模型量化/部署参考流程；同时保留 Cortex-M55 作为算子兜底（CMSIS-NN）。MPU 档沿用 ST 系列，保证 MCU/MPU 双档共用一套模型打包格式与 OTA 通道。

## 2.2 端侧软件分层

| 层 | 职责 | 关键模块 |
|---|---|---|
| BSP/HAL | 时钟、电源域、音频 DMA、显示、灯环、电池 | `audio_engine`、`power_manager`、`display_ui` |
| RTOS 层 | FreeRTOS 多任务、任务间队列与事件组 | 任务优先级与栈预算见 2.4 |
| 音频子系统 | 采集、AEC、AGC、NS、重采样、环形缓冲、播放 | 16k mono PCM 内部统一格式 |
| 感知层 | VAD、唤醒、端侧 ASR、端侧意图模型 | `vad_engine`、`asr_engine`、`intent_engine` |
| 对话层 | 端侧 LLM 推理、澄清状态机、打断管理 | `llm_runtime`、`dialog_manager` |
| 表达层 | 端侧 TTS 或提示音、表情/灯光驱动 | `tts_local`、`emotion_renderer` |
| 设备管理 | 配网、BLE、OTA、配置、遥测、调试通道 | `ota_client`、`telemetry` |
| 业务层 | 会话状态、记忆缓存、用户偏好本地副本 | `session_state`、`local_profile` |

**分层依赖单向**：上层可调用下层 API，下层不得反向依赖；跨层通信一律走事件/队列，禁止直接调用。

## 2.3 音频前端规范

| 项 | 规格 | 说明 |
|---|---|---|
| 采样率 | 输入 48kHz → 内部统一 16kHz mono | 送模型一律 16k/16bit |
| 帧长 | 20ms/帧（320 样本） | VAD 与 ASR 最小单元 |
| 缓冲 | 采集环形缓冲 3s + 上行队列 10s | 上行队列满则丢最旧帧并上报 |
| AEC | 硬件/软件 AEC，参考通道取自功放回采 | 免提模式必备 |
| 降噪 | AGC + NS + 高通 80Hz | 抑制空调/风扇噪声 |
| 编码 | 上行可选 PCM / Opus(16k, 24kbps) | 4G 网络下用 Opus，带宽降 78% |
| 播放 | 缓冲 ≥ 200ms，首包直发 | 避免下句被上一句截断 |

## 2.4 RTOS 任务与内存预算（MCU 档）

| 任务 | 优先级 | 栈 | 周期 | 说明 |
|---|---|---|---|---|
| `audio_capture` | 最高 | 2KB | 20ms | DMA 半满中断驱动 |
| `vad_task` | 高 | 2KB | 20ms | 判定人声/静音事件 |
| `asr_task` | 高 | 8KB | 事件 | whisper.cpp 流式解码（**仅 MPU 档**，见 P0-1） |
| `intent_task` | 中 | 4KB | 事件 | 规则 + LoRA 分类模型 |
| `llm_task` | 中 | 6KB | 事件 | 0.5B 生成（**仅 MPU 档**，MCU 档裁掉） |
| `net_task` | 中 | 6KB | 事件 | MQTT/TLS/上行下行动 |
| `ui_task` | 低 | 3KB | 50ms | 屏显、灯环、表情渲染 |
| `ota_task` | 低 | 4KB | 事件 | 差分包下载与校验 |

静态内存占用目标：SRAM ≤ 70%（约 1.75MB），TCM 放模型激活与热代码，NOR 32MB 分区见 4.6。

> **P0-4 修订说明**：§2.1 的 MCU 档仅 2.5MB SRAM + 4MB TCM，而 §4.8 的准入门槛写"MCU 档 RAM 峰值 ≤ 2MB"。whisper 在 512 token 上下文下的 KV cache 与激活峰值常达 1.5–2MB，叠加 TCM、音频缓冲与 RTOS 栈后无余量。本方案据此调整：**MCU 档取消 ASR 后不再承载 whisper 的 KV cache**，MCU 档内存门槛收紧为 ≤ 1.2MB（意图模型激活 + 音频缓冲 + RTOS 栈）；MPU 档 ASR 上下文上限设为 **256 token**（≈15 秒语音足够），激活 INT8 量化，KV cache 放 DDR。详见 §12.1 P0-4。

## 2.5 电源与功耗档位

| 状态 | 触发 | 目标功耗 | 行为 |
|---|---|---|---|
| 深度睡眠 | 无人声 > 30s | ≤ 0.3 mW | 仅保留 RTC + 唤醒词检测（MCU 档）/ 接近传感（MPU 档） |
| 待机 | 有人声但未唤醒 | ≤ 60 mW | VAD 常开，ASR 关闭 |
| 交互 | 对话中 | ≤ 4.5W（MPU 档） | ASR + LLM + 网络 + 播放 |
| 播放 | TTS 输出 | ≤ 2.8W | NPU 空闲，MPU 低频 |
| 充电 | 接电 | — | 温控限流，充电时允许全速推理 |

**MPU 档热设计**：DDR 512MB 起步，NPU 推理温度上限 85℃，超过 70℃ 触发限频（推理速度降 30% 并保底体验）。MCU 档无风扇，靠外壳散热，导热垫贴 NPU。
