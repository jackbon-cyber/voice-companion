# 6. 语音输出：TTS、音色克隆与情感表达

## 6.1 TTS 选型与部署

| 方案 | 优点 | 缺点 | 结论 |
|---|---|---|---|
| Qwen2.5-Omni-TTS（自建部署） | 音色克隆能力强、支持情感指令、指令跟随好、与 Qwen 系模型同源便于统一运维 | 需 GPU 推理，单价高，长文本首包慢 | **主用**：情感陪伴 + 克隆音色 |
| 第三方商用 TTS（通用音色库） | 稳定、首包快、成本可控 | 情感表达弱、无法克隆 | **备选/降级**：云端过载或非克隆音色时切换 |
| 端侧轻量 TTS | 断网可用、零边际成本 | 音质与情感上限明显低于云端 | **仅兜底**：L2 降级档使用 |

**部署形态**：`tts-service` 自建 GPU 推理集群（vLLM / TensorRT-LLM 承载 Omni-TTS），按并发路数扩缩容；模型与 prompt 模板通过 Nacos 热更。

**流式合成**：文本按标点切成句级片段，边生成边下发，首片段只做一次前向（短句），把首包压到 380ms 以内。

```python
# tts-service：句级流式切分 + 首片段短句优先，降低首包延迟
SENTENCE_END = "。！？；!?;\n"
MAX_FIRST_CHUNK = 12   # 首片段最多 12 字，用于抢首包

def split_for_streaming(text: str, first_chunk_limit: int = MAX_FIRST_CHUNK) -> list[str]:
    """按句末标点切分；首片段裁短以抢首包，其余片段按语义长度合并。"""
    parts = [p for p in re.split(f"({SENTENCE_END})", text) if p.strip()]
    chunks: list[str] = []
    buffer = ""
    for part in parts:
        buffer += part
        if buffer and (part[-1] in SENTENCE_END or len(buffer) >= 40):
            chunks.append(buffer)
            buffer = ""
    if buffer:
        chunks.append(buffer)
    if len(chunks) > 1 and len(chunks[0]) > first_chunk_limit:
        head = chunks[0][:first_chunk_limit]
        rest = chunks[0][first_chunk_limit:] + "".join(chunks[1:])
        chunks = [head] + [rest]
    return chunks
```

## 6.2 音色克隆流程

**流程（与仓库既有"授权 + 水印"要求一致）**：

```
① 用户提交 3–5 分钟干净录音（授权书勾选）＋ 目标音色描述
② 服务端音频质检：信噪比 ≥ 20dB、无背景音乐、无多人说话、时长合规
③ 声音特征提取 → 音色向量（speaker embedding）
④ 合成试听样例 → 用户试听确认（不满意可重录，最多 3 次）
⑤ 音色入库，绑定 personaId，记录授权人、授权时间、授权范围（用途/期限/地域）
⑥ 推理时携带 speakerId + emotion 标签，生成带水印的音频
```

**水印与溯源**：合成音频嵌入不可感知水印（频率域扰动），设备端播放前不剥离，平台侧保留 `speakerId → 授权单号 → 使用记录` 链路，用于溯源滥用。

**音色库存储**：

| 表 | 字段 | 说明 |
|---|---|---|
| `voice_profile` | id, name, owner_id, auth_doc_uri, auth_scope, auth_expire_at, status, created_at | 授权与状态 |
| `voice_embedding` | voice_id, embedding(vector), model_version | 音色向量 |
| `voice_sample` | voice_id, sample_uri, qc_result | 试听样例与质检结果 |

**合规红线**：音色克隆必须有人声授权；未授权克隆入口在产品上不可见；授权到期自动停用音色；未成年人音色克隆入口关闭。

## 6.3 情感表达与多模态反馈

| 通道 | 参数 | 实现 |
|---|---|---|
| 语音情感 | `emotion` 标签 + 强度（0–1） | TTS 的情感指令，标签集：neutral/warm/cheerful/sad/anxious/soothing/playful |
| 语音韵律 | 语速、音量、停顿 | 依用户语速偏好 ±20% 范围调整 |
| 灯光 | RGB 颜色 + 呼吸频率 | 情绪色映射表，柔和渐变 |
| 表情 | 屏显表情 | 与情绪标签 1:1 映射，屏显滞后音频 ≤ 200ms |
| 动作 | 机身轻动/点头（MPU 档） | 情绪强时触发，幅度可关 |

**情绪标签的来源优先级**：用户显式表达 > 端侧情感分类模型 > 云端情绪识别 > 默认 neutral。冲突时以显式表达为准。

**情绪标签到 TTS 的映射**：主 Agent 生成回复时**同时产出情绪标签**（结构化输出 `text` + `emotion`），避免额外一次模型调用。

## 6.4 音频下行与播放

| 项 | 规格 |
|---|---|
| 编码 | PCM 16k/16bit（带宽充足场景）或 Opus 24kbps（弱网） |
| 分片 | 100ms 一片，带序号；乱序缓冲 200ms |
| 缓冲策略 | 首包直发（不等全量），后续包可攒 2 片再发以省包头 |
| 打断 | 收到 `interrupt` 事件立即清空下行缓冲并停播（≤ 80ms） |
| 播放打断回声 | 播放期间 AEC 参考通道必须打开，否则 VAD 会把自身声音当用户 |
