# 模型包格式

> 统一模型包是端侧模型的**分发产物**：打包脚本产出它，设备端安装它。
> MCU 档与 MPU 档共用同一套包格式与 OTA 通道。

## 目录

| 路径 | 内容 |
|---|---|
| `manifest.schema.json` | 清单格式定义（JSON Schema Draft 2020-12）。**权威定义**。 |
| `package_model.py` | 打包脚本：生成清单、计算 sha256、签名。 |

## 包结构

```
companion_model_pkg/
├── manifest.json          # 清单：包版本 / 目标平台 / 模型列表 / 兼容区间 / 验签信息
├── models/
│   ├── intent_lora.int8.onnx        (16MB)
│   ├── emotion_clf.int8.onnx        (6MB)
│   ├── kws.tflite                   (1MB)
│   └── llm_lora_0_5b.q4_k_m.gguf    (400MB, MPU 档)
└── signature.sig         # 设备端用内嵌公钥验签
```

## 与技术架构方案 §4.6 的偏离

方案里写的是单一文件 `companion_model_pkg.bin`。**本参考实现不用自定义容器格式**，
而是"目录 + `manifest.json` 描述布局"。

**为什么偏离**：

| 方案（自定义 `.bin`） | 本实现（目录 + 清单） |
|---|---|
| 需要额外写解包器 | 直接读目录下的文件 |
| 解包器失败模式复杂（内存不足、越界、长度校验） | 没有解包器就没有这类失败 |
| 设备端 flash 布局必须与容器格式绑定 | 布局由设备端决定 |

容器格式的收益是"单文件分发更省事"，代价是解包器成为新的失败点。
在 flash 32MB / 内存紧张的 MCU 上，一个有 bug 的解包器足以让 OTA 变成砖机事故。
**容器格式留给量产固件决定** —— 那时 flash 布局与镜像格式是同一件事，
由同一份工具链产出，没有额外风险。

## 清单字段

| 字段 | 必填 | 说明 |
|---|---|---|
| `packageVersion` | 是 | 模型包自身版本号。 |
| `platform` | 是 | 目标平台标识。 |
| `models` | 是 | 模型列表，**不得为空**。 |
| `models[].id` | 是 | 模型标识。 |
| `models[].version` | 是 | 模型版本号，用于版本台账与回滚点定位。 |
| `models[].file` | 是 | 包内相对路径，必须在 `models/` 下。**不允许路径穿越**。 |
| `models[].size` | 是 | 字节数。 |
| `models[].sha256` | 是 | 64 位十六进制小写。设备端下载后逐块校验。 |
| `models[].minRuntime` | 是 | 可加载该模型的最低运行时版本。 |
| `compat.firmwareMin` / `compat.firmwareMax` | 是 | 固件兼容区间。区间外不装。 |
| `rollbackPartition` | 是 | 安装失败回滚到的分区，**只能是 `A` 或 `B`**。 |
| `signatureAlgorithm` | 是 | 验签算法，当前为 `Ed25519`。 |
| `signatureFile` | 是 | 签名文件相对路径。 |

### 为什么收紧这几项

- **`rollbackPartition` 收紧为枚举**：自由字符串下写成 `"C"` 或 `"a"` 都不会报错，
  而设备端会把它当成"回滚到未知分区" —— 回滚路径失效是 OTA 最严重的失败形态。
- **`signatureAlgorithm` 收紧为枚举**：算法名写错时设备端报"签名无效"，
  但真实原因是名字拼错，排查方向会被带偏。
- **`models[].sha256` 必填且定长**：没有校验和的模型文件，设备端无法判断下载是否损坏 ——
  装上一个截断的模型，表现为"模型加载失败"，排查方向完全跑偏。
- **未知字段一律拒绝**：与端云协议同一条理由。多出的字段说明打包端与设备端版本已错位，
  静默忽略会让错位无法被发现。

## schema 管不了的事

**`compat.firmwareMin > compat.firmwareMax` 不由 schema 校验**。
JSON Schema Draft 2020-12 没有跨字段的语义化版本比较能力；
用 pattern 近似（比较字典序）会在带预发布标识的版本号上出错，比不校验更糟。

该不变量由**打包脚本**强制（见 `package_model.py` 的 `validate_manifest`）。

## 签名

**Ed25519**（`cryptography` 库），不用 RSA。

理由：Ed25519 签名短（64 字节）、验签快、**无需证书链** ——
设备端只嵌一把公钥就能验签，不需要维护 CA。
代价：新增 `cryptography` 依赖。

**验签失败即丢弃，绝不尝试安装。**

## 打包

```powershell
# 生成签名密钥（只需一次；私钥不得入库）
F:\tools\python313\python.exe device-ref\model-package\package_model.py `
    --gen-key device-ref\model-package\keys\device_sign_key.pem

# 打包
F:\tools\python313\python.exe device-ref\model-package\package_model.py `
    --manifest build\manifest.json `
    --out dist\companion_model_pkg `
    --sign-key device-ref\model-package\keys\device_sign_key.pem
```

## 校验

```powershell
F:\tools\python313\python.exe -m pytest core\tests\device_ref -v
```
