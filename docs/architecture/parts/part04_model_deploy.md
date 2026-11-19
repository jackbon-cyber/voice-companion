# 4. 端侧模型：训练、量化、部署与 OTA

本章是"本地小模型如何真正跑到端侧"的完整落地路径，从语料到设备上运行的每一步都给出可执行命令与产物。

![端侧模型训练部署流水线](assets/端侧模型训练部署流水线.png)

## 4.1 模型清单与分工

| 模型 | 用途 | 底座 | 微调方式 | 部署位置 |
|---|---|---|---|---|
| `vad_silero` | 人声检测 | Silero VAD | 不微调（已有 INT8） | MCU + MPU |
| `kws` | 唤醒词 | 自训小 CNN/DS-CNN | 全参或 LoRA | MCU |
| `asr_whisper` | 语音转文字 | whisper tiny/base | 领域热词 + 不微调权重 | MCU（tiny）/ MPU（base） |
| `intent_lora` | 意图 + 槽位 | MiniLM-L6 | LoRA | MCU + MPU |
| `llm_lora_0_5b` | 端侧兜底对话 | Qwen2.5-0.5B | LoRA | MPU |
| `emotion_clf` | 情感初判（正/负/中） | MiniLM-L6 | LoRA | MCU + MPU |
| `tts_local` | 端侧 TTS | 轻量 VITS/自研声码器 | 全参微调 + 量化 | MPU（可选，二期） |

## 4.2 第一步：数据构建

**数据来源三类**：

| 来源 | 内容 | 量级 |
|---|---|---|
| 合成 | 用云端大模型按人设卡生成多轮陪伴对话（角色扮演 + 澄清样本） | 30 万条 |
| 众包 | 真人语音录制（需授权书）+ 人工转写 | 2 万小时 ASR / 5000 条意图 |
| 公开 | 开源中文对话、情感语料（需审许可） | 20 万条 |

**清洗规则（脚本化，可复跑）**：

```python
# tools/data/clean_corpus.py —— 语料清洗：去重、脱敏、长度过滤、角色一致性检查
MAX_SEQ_LEN = 512          # 端侧上下文上限，超长样本直接截断并丢弃
DEDUP_THRESHOLD = 0.92    # MinHash Jaccard 阈值，>0.92 视为重复
PII_PATTERNS = [r"\d{17}[\dXx]", r"\d{11}", r"[\w.+-]+@[\w-]+\.[\w.]+"]
ROLE_CONFLICT_KEYS = ["系统", "助手", "用户"]  # 角色标签不一致的样本需人工复核

def is_valid(sample: dict) -> bool:
    """返回 True 表示样本进入训练集；不满足任一条件即丢弃并记录原因。"""
    if len(sample["messages"]) < 2:
        return False
    if token_len(sample) > MAX_SEQ_LEN:
        return False
    if contains_pii(sample["text"]):
        return False
    if has_role_conflict(sample):
        return False
    return True
```

**数据配比（经验值，需按评测集调整）**：

| 任务 | 配比 | 说明 |
|---|---|---|
| 陪伴闲聊 | 45% | 主体，覆盖 6 类情绪 |
| 角色扮演 | 20% | 严格按人设卡，注入越界样本（问"你真的是人吗"）做拒答训练 |
| 澄清样本 | 15% | 槽位缺失、歧义、指代不明 |
| 设备控制 | 10% | 意图模型的训练集主体 |
| 安全拒答 | 10% | 违规诱导、自伤、医疗建议边界 |

**质量门禁**：训练集与评测集**互斥**，按 `session_id` 切分；任何训练样本不得出现在评测集。

## 4.3 第二步：LoRA 微调

**工具**：LLaMA-Factory（或 ms-swift）统一训练入口，配置入库，便于复跑。

```yaml
# configs/train/llm_lora_0_5b.yaml
### model
model_name_or_path: Qwen/Qwen2.5-0.5B-Instruct
trust_remote_code: true

### method：LoRA 只训练低秩适配器，不动基座权重，产物小、可多版本并存
lora_rank: 16
lora_alpha: 32
lora_dropout: 0.05
lora_target: all            # q,k,v,o,gate,up,down 全覆盖

### dataset
dataset: data/companion_chat.json
template: qwen
cutoff_len: 512
overwrite_cache: true
preprocessing_num_workers: 16
dataloader_num_workers: 4

### output
output_dir: saves/llm_lora_0_5b/v1
logging_steps: 10
save_steps: 500
plot_loss: true
overwrite_output_dir: true

### train
per_device_train_batch_size: 8
gradient_accumulation_steps: 4
learning_rate: 1.0e-4
num_train_epochs: 3.0
lr_scheduler_type: cosine
warmup_ratio: 0.1
bf16: true
gradient_checkpointing: true
val_size: 0.02
```

```bash
# 训练（单机 2 卡 A10 即可，单卡约 6 小时）
llamafactory-cli train configs/train/llm_lora_0_5b.yaml
# 产出：saves/llm_lora_0_5b/v1/adapter_model.safetensors  (约 60MB)
```

**意图模型（MiniLM）训练**：

```bash
python -m intent_lora.train \
  --base_model microsoft/MiniLM-L6-H384 \
  --train data/intent/train.jsonl \
  --eval  data/intent/dev.jsonl \
  --lora_rank 16 --lora_alpha 32 --targets query,key,value \
  --output saves/intent_lora/v1 --epochs 8 --batch 32 --lr 3e-4
```

**合并基座与适配器**（部署前必须做，否则端侧加载器不支持 adapter）：

```bash
# 合并 LoRA 到基座，得到可直接量化的完整权重
python scripts/merge_lora.py \
  --base  Qwen/Qwen2.5-0.5B-Instruct \
  --lora  saves/llm_lora_0_5b/v1 \
  --out   artifacts/llm_lora_0_5b/merged_bf16 --dtype bfloat16
```

## 4.4 第三步：量化

**两条路线，按端侧硬件选**：

| 路线 | 工具 | 产物 | 适用 |
|---|---|---|---|
| 静态 INT8（PTQ） | `llama.cpp` 的量化脚本 / `onnxruntime quantization` | `*.int8.bin` 或 `*.onnx` | MCU 档 NPU（Ethos-U55 需 INT8） |
| GGUF | `llama-quantize` | `*.q4_k_m.gguf` | MPU 档 CPU/NPU 混合推理，体积与速度平衡最好 |

```bash
# 路线 A：GGUF Q4_K_M（M4_K_M 在 4bit 档里质量损失最小、体积最适中）
llama-quantize artifacts/llm_lora_0_5b/merged_bf16/model-00001-of-00002.safetensors \
                  artifacts/llm_lora_0_5b/q4_k_m.gguf Q4_K_M

# 路线 B：ONNX + 动态量化（供 MCU/MCU 档 NPU）
python scripts/export_onnx.py --model artifacts/llm_lora_0_5b/merged_bf16 --out artifacts/onnx/model_fp32
python -m onnxruntime.quantization.quantize_static \
  --model artifacts/onnx/model_fp32.onnx \
  --weight_format int8 --activation_format int8 \
  --calibration_data_reader scripts/calib_reader.py \
  --quantized_model artifacts/onnx/model_int8.onnx
```

**量化校准数据要求**：从真实陪伴对话采样 ≥ 512 条，覆盖短句/长句/带情绪/带数字/带英文五类；校准集与评测集不相交。

**量化质量验收**（不达标不得进端侧）：

| 指标 | 门限 | 说明 |
|---|---|---|
| 量化前后困惑度 PPL 增幅 | ≤ 8% | `merged_bf16` vs `q4_k_m` 在同校准集上对比 |
| 意图准确率下降 | ≤ 1.5pt | 意图模型 INT8 与 FP32 对比 |
| 拒答准确率下降 | ≤ 1pt | 安全样本必须更敏感（宁可多拒） |

## 4.5 第四步：端侧编译与算子覆盖检查

**这是"能不能跑在 NPU 上"的关键一步，也是最容易翻车的一步。**

```bash
# ST Edge AI Core：模型编译 + NPU delegate 映射
stedgeai generate --model artifacts/onnx/model_int8.onnx \
                  --target stm32n6-npu \
                  --output artifacts/stedgeai/llm_int8 \
                  --arena-size 2097152 \
                  --report artifacts/stedgeai/op_support_report.txt
```

**算子覆盖检查规则**（脚本断言，不通过即构建失败）：

```
必须满足：
  1. NPU 支持算子占比 = 100%（UNSUPPORTED_OP_COUNT == 0）
  2. 未命中算子必须全部落到 CMSIS-NN CPU 兜底路径，且单层 CPU 占比 < 5%
  3. 静态内存 arena ≥ 实际激活峰值 + 30% 余量
  4. 若采用动态 shape → 必须在编译期固定为单 shape（batch=1, seq=512）
```

**MPU 档路径**：

```bash
# ExecuTorch 导出 + Ethos-U85 后端
python scripts/export_executorch.py --model artifacts/onnx/model_int8.onnx --out artifacts/execu/llm_int8.et
# llama.cpp 路径（GGUF）
./llama.cpp/build/bin/llama-cli -m artifacts/llm_lora_0_5b/q4_k_m.gguf -p "你好，今天有点累" -n 64 -t 4
```

## 4.6 第五步：模型包格式与 OTA

**统一模型包（所有模型共用同一容器）**：

```
companion_model_pkg.bin
├── manifest.json          # 模型清单：id/版本/hash/目标平台/大小/校验
├── models/
│   ├── intent_lora.int8.onnx        (16MB)
│   ├── emotion_clf.int8.onnx        (6MB)
│   ├── kws.tflite                   (1MB)
│   └── llm_lora_0_5b.q4_k_m.gguf    (400MB, MPU 档)
├── runtime/
│   ├── stedgeai_runtime.so           (MCU) / executorch.so (MPU)
│   └── tokenizer.model
└── signature.sig                     # 设备端公钥验签
```

```json
{
  "package_version": "1.4.0",
  "platform": "stm32mpu257",
  "models": [
    {"id": "llm_lora_0_5b", "version": "3", "file": "models/llm_lora_0_5b.q4_k_m.gguf",
     "size": 419430400, "sha256": "…", "min_runtime": "1.2.0"},
    {"id": "intent_lora", "version": "7", "file": "models/intent_lora.int8.onnx",
     "size": 16777216, "sha256": "…", "min_runtime": "1.2.0"}
  ],
  "compat": {"firmware_min": "2.1.0", "firmware_max": "2.9.x"},
  "rollback_partition": "B"
}
```

**OTA 流程（A/B 双分区）**：

```
设备上报当前版本 → 云端下发目标包 URL + sha256 + 签名
   → 设备下载到备用分区（B），边下边校验 sha256
   → 下载完成 → 设备用内嵌公钥验签 signature.sig（失败即丢弃，不尝试安装）
   → 写 manifest → 置 boot_flag=B → 重启
   → 新固件启动后自检：模型能加载 + 推理冒烟测试（固定 3 条样本，输出非空且非乱码）
   → 自检通过 → 上报 healthy → 固化；自检失败 → 自动回滚 boot_flag=A
   → 云端观察 15 分钟指标，异常则下发回滚指令
```

```bash
# 打包
python scripts/package_model.py --manifest build/manifest.json --out dist/companion_model_pkg.bin --sign-key $DEVICE_SIGN_KEY
# 灰度下发（1% → 5% → 20% → 50% → 100%）
curl -X POST http://ota-gateway/rollout -d '{"package":"companion_model_pkg.bin","stage":5,"target":"staging"}'
```

**断点续传**：下载以 64KB 块为单位记录位图到 Flash，续传时从缺失块补齐；断网重连后自动续传。

## 4.7 第六步：灰度与回滚指标

| 阶段 | 流量 | 通过条件 | 不通过动作 |
|---|---|---|---|
| 影子模式 | 5%（只记录不生效） | 推理成功率 ≥ 99.5%，无崩溃 | 停推 |
| 小流量 | 5% | 意图准确率下降 ≤ 1pt | 回滚 |
| 中流量 | 20% | 端侧首 token P95 ≤ 250ms | 限速灰度 / 回滚 |
| 全量 | 100% | 崩溃率 < 0.1%，耗电不高于基线 15% | 回滚 |

**版本台账**：每次发布记录模型版本、训练数据版本、量化配置、评测分数、回滚点。台账缺失不允许发布。

## 4.8 端侧模型准入门槛（Gate）

任一项不满足，模型不得下发设备：

| 指标 | MCU 档 | MPU 档 |
|---|---|---|
| 权重体积 | ≤ 16MB | ≤ 900MB |
| RAM 峰值 | **≤ 1.2MB**（原 2MB，MCU 档已无 whisper，见 P0-4） | ≤ 1.2GB |
| 单次推理 | ≤ 120ms | 首 token ≤ 250ms |
| 算子覆盖 | NPU 100%，未命中 CPU 兜底 < 5% | 同左，CPU 兜底 < 10% |
| 功耗 | ≤ 1.2W | ≤ 3.5W |
| 精度 | 相对 FP32 下降 ≤ 1.5pt | ≤ 2pt |
| 回滚能力 | A/B 分区 + 5 分钟内可回退 | 同左 |

> **P0-4 修订说明**：MCU 档取消端侧 ASR 后不再承载 whisper 的 KV cache（原为 512 token，约 1.5–2MB），内存门槛由 ≤ 2MB 收紧为 ≤ 1.2MB；MPU 档 ASR 上下文上限设为 256 token 以控制 KV cache 占用。详见 §12.1 P0-4。

## 4.9 端侧目录结构（MCU 档为例）

```
firmware/
├── app/
│   ├── main/                 # 启动、任务创建、电源管理
│   ├── audio/                # 采集/AEC/AGC/环形缓冲/播放
│   ├── perception/           # vad_engine, asr_engine, intent_engine, kws
│   ├── dialog/               # llm_runtime, dialog_manager, interrupt
│   ├── expression/           # tts_local, emotion_renderer
│   ├── device/               # ota_client, telemetry, config_client
│   └── business/             # session_state, local_profile
├── models/                   # 模型包解包后的只读区（映射 NOR）
├── third_party/
│   ├── whisper.cpp/
│   ├── cmsis-nn/
│   ├── st_edge_ai_core/
│   └── llama.cpp/
├── configs/
│   ├── model_manifest.json
│   └── intent_rules.json     # 规则表（端侧硬规则，可热更新）
└── build/
    ├── Makefile
    └── linker/               # 各分区 ld script
```
