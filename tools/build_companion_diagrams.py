"""语音情感陪伴机器人 架构图生成脚本（端云协同 / 端侧模型流水线 / 记忆与千人千面 / 实时会话时序）。

风格对齐 tools/build_arch_diagram.py：微软雅黑 + PIL 手绘 + 胶囊卡片。
输出：docs/architecture/assets/*.png

用法（在仓库根目录执行）：
    F:\\tools\\python313\\python.exe tools\\build_companion_diagrams.py
"""
from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
OUT_DIR = os.path.join(ROOT, "docs", "architecture", "assets")

FONT_REGULAR = r"C:\Windows\Fonts\msyh.ttc"
FONT_BOLD = r"C:\Windows\Fonts\msyhbd.ttc"

BG = (255, 255, 255)
INK = (24, 42, 62)
INK_SOFT = (92, 110, 128)
LINE = (206, 218, 230)
BAND = (244, 248, 251)
CARD = (252, 253, 254)

EDGE = (0, 106, 152)      # 端侧
CLOUD = (110, 76, 172)    # 云端
MEM = (188, 108, 20)      # 记忆
MODEL = (0, 132, 116)     # 模型
WARN = (176, 58, 74)      # 风险/合规
NEUTRAL = (72, 92, 120)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR, size)


def wrap(draw, text: str, fnt, max_w: int) -> list[str]:
    lines: list[str] = []
    for para in text.split("\n"):
        if not para:
            lines.append("")
            continue
        cur = ""
        for ch in para:
            trial = cur + ch
            if draw.textlength(trial, font=fnt) <= max_w:
                cur = trial
                continue
            if ch.isalnum() and " " in cur.strip():
                head, _, tail = cur.rstrip().rpartition(" ")
                if head:
                    lines.append(head)
                    cur = tail + ch
                    continue
            lines.append(cur)
            cur = ch
        if cur:
            lines.append(cur)
    return lines


def draw_centered(draw, box, text, fnt, fill, gap=5):
    x0, y0, x1, y1 = box
    lines = wrap(draw, text, fnt, x1 - x0)
    lh = fnt.size + gap
    y = y0 + (y1 - y0 - lh * len(lines)) / 2
    for ln in lines:
        w = draw.textlength(ln, font=fnt)
        draw.text((x0 + (x1 - x0 - w) / 2, y), ln, font=fnt, fill=fill)
        y += lh


def rounded(draw, rect, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(rect, radius=radius, fill=fill, outline=outline, width=width)


def card(draw, rect, title, lines, accent, title_size=24, body_size=17, fill=CARD, tag=None):
    rounded(draw, rect, 10, fill, accent, 2)
    draw.rounded_rectangle((rect[0], rect[1], rect[0] + 8, rect[3]), radius=4, fill=accent)
    y = rect[1] + 12
    draw.text((rect[0] + 22, y), title, font=font(title_size, True), fill=accent)
    y += title_size + 8
    if tag:
        draw.text((rect[0] + 22, y), tag, font=font(body_size - 1, True), fill=INK)
        y += body_size + 4
    for line in lines:
        for ln in wrap(draw, line, font(body_size), rect[2] - rect[0] - 44):
            draw.text((rect[0] + 22, y), ln, font=font(body_size), fill=INK_SOFT)
            y += body_size + 8
        y += 3
    return y


def arrow(draw, p1, p2, color, width=3, label=None, font_size=16):
    draw.line((p1[0], p1[1], p2[0], p2[1]), fill=color, width=width)
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    length = max((dx ** 2 + dy ** 2) ** 0.5, 1)
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    tip = (p2[0], p2[1])
    base = (p2[0] - ux * 14, p2[1] - uy * 14)
    draw.polygon([tip, (base[0] + px * 6, base[1] + py * 6), (base[0] - px * 6, base[1] - py * 6)], fill=color)
    if label:
        tw = draw.textlength(label, font=font(font_size))
        mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
        draw.rectangle((mx - tw / 2 - 5, my - font_size - 4, mx + tw / 2 + 5, my + 4), fill=BG)
        draw.text((mx - tw / 2, my - font_size - 2), label, font=font(font_size), fill=INK)


# ---------------------------------------------------------------- 总体架构图
def build_overview() -> str:
    W, H = 3000, 2340
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    x = 70
    w = W - 140

    d.text((x, 46), "语音情感陪伴机器人 · 端云协同总体架构", font=font(52, True), fill=INK)
    d.text((x, 112), "STM32N6(Edge NPU) │ 端侧 ASR/VAD/小模型 │ 云端 AgentScope 多智能体 │ Chroma 记忆 ｜ 四级降级链路",
           font=font(24), fill=INK_SOFT)
    d.line((x, 158, x + w, 158), fill=LINE, width=3)

    # 左：端侧域
    edge_box = (x, 200, x + 880, 1980)
    rounded(d, edge_box, 14, (246, 251, 254), EDGE, 3)
    d.text((x + 26, 218), "端侧域（STM32N6 + Ethos-U55 NPU）", font=font(28, True), fill=EDGE)

    edge_rows = [
        ("音频前端", ["麦克风阵列 / 回声消除", "环形缓冲 20ms", "AGC 降噪", "PCM 16k mono"], "采样与播放"),
        ("唤醒与 VAD", ["Silero VAD (ONNX INT8)", "WebRTC VAD 三级", "端侧语音活动检测", "静音 800ms 断句"], "有人声判定"),
        ("端侧 ASR", ["whisper.cpp tiny/base", "INT8 量化 40–90MB", "流式 chunk 推", "热词词表注入"], "本地文字"),
        ("端侧小模型", ["意图分类 MiniLM+LoRA", "槽位抽取 / 情感初判", "INT8 ≤ 16MB Flash", "ST Edge AI Core 推理"], "端侧预判"),
        ("端侧对话", ["0.5B LoRA 合并模型", "Q4_K_M GGUF / ONNX", "llama.cpp on MPU", "简单陪伴直接应答"], "低时延兜底"),
        ("端侧控制", ["BLE 配网 / OTA", "提示音与灯光情绪", "按键打断 barge-in", "本地缓存话术"], "设备行为"),
    ]
    y = 266
    for name, comps, note in edge_rows:
        rect = (x + 26, y, x + 854, y + 250)
        rounded(d, rect, 10, CARD, EDGE, 2)
        d.text((rect[0] + 20, rect[1] + 14), name, font=font(24, True), fill=EDGE)
        cx = rect[0] + 20
        cy = rect[1] + 54
        for c in comps:
            cw = min(250, 380)
            rounded(d, (cx, cy, cx + cw, cy + 36), 8, (250, 253, 255), LINE, 1)
            draw_centered(d, (cx + 4, cy, cx + cw - 4, cy + 36), c, font(16), INK_SOFT)
            cx += cw + 10
            if cx + cw > rect[2] - 200:
                cx = rect[0] + 20
                cy += 44
        d.text((rect[2] - 190, rect[1] + 14), note, font=font(20, True), fill=EDGE)
        d.text((rect[2] - 190, rect[1] + 48), "产出 → 上行", font=font(16), fill=INK_SOFT)
        y += 268

    # 右侧云端域
    cloud_x = x + 980
    cloud_box = (cloud_x, 200, x + w, 1980)
    rounded(d, cloud_box, 14, (250, 248, 253), CLOUD, 3)
    d.text((cloud_x + 26, 218), "云端域（K8s + AgentScope 2.0.4 Java）", font=font(28, True), fill=CLOUD)

    cloud_rows = [
        ("接入层", ["边缘网关 / MQTT+WS", "设备鉴权 mTLS", "会话保持", "流式音频通道", "限流熔断"], "端云协议"),
        ("ASR 服务", ["FunASR / Paraformer", "流式识别 + 标点", "热词定制", "方言适配"], "云侧兜底 ASR"),
        ("意图服务", ["规则引擎 200+ 规则", "端侧小模型初判", "云端 LLM 分类", "多轮澄清状态机"], "意图 + 槽位"),
        ("Agent 编排", ["主 Agent ReAct", "情感陪伴 Agent", "角色扮演 Agent", "工具 / Skill 调用", "输出治理"], "生成回复"),
        ("记忆服务", ["短期 / 工作记忆", "长期语义记忆 Chroma", "情景记忆", "用户画像偏好", "衰减与归并"], "千人千面"),
        ("TTS 服务", ["Qwen2.5-Omni-TTS", "音色克隆 / 情感注入", "流式分片合成", "PCM 16k 下发"], "语音下行"),
        ("安全合规", ["未成年人模式", "内容审核双向", "声音授权与水印", "隐私脱敏", "审计留痕"], "红线"),
    ]
    cy0 = 266
    for name, comps, note in cloud_rows:
        rect = (cloud_x + 26, cy0, x + w - 26, cy0 + 232)
        rounded(d, rect, 10, CARD, CLOUD, 2)
        d.text((rect[0] + 20, rect[1] + 14), name, font=font(24, True), fill=CLOUD)
        cx = rect[0] + 20
        cy = rect[1] + 54
        for c in comps:
            cw = 236
            rounded(d, (cx, cy, cx + cw, cy + 36), 8, (252, 250, 254), LINE, 1)
            draw_centered(d, (cx + 4, cy, cx + cw - 4, cy + 36), c, font(16), INK_SOFT)
            cx += cw + 10
            if cx + cw > rect[2] - 200:
                cx = rect[0] + 20
                cy += 44
        d.text((rect[2] - 176, rect[1] + 14), note, font=font(20, True), fill=CLOUD)
        cy0 += 250

    # 中间链路箭头
    mid = x + 880
    d.text((mid + 20, 380), "上行：PCM/文本/意图特征", font=font(18, True), fill=EDGE)
    arrow(d, (x + 880, 420), (cloud_x, 420), EDGE, 4)
    d.text((mid + 20, 460), "下行：流式 PCM + 情绪事件", font=font(18, True), fill=CLOUD)
    arrow(d, (cloud_x, 500), (x + 880, 500), CLOUD, 4)

    # 底部：降级矩阵
    band = (x, 2020, x + w, 2280)
    rounded(d, band, 12, (250, 247, 240), (230, 200, 150), 2)
    d.text((x + 26, 2036), "四级降级策略（网络分区 / 云端过载时逐级下探）", font=font(26, True), fill=(150, 96, 24))
    rows = [
        ("L0 正常", "端侧 ASR + 云端 LLM + 云端 TTS", "延迟目标 ≤ 1.8s（首字到出声）"),
        ("L1 弱网", "端侧 ASR + 云端轻量意图 + 云端 TTS 流式首包", "丢包重传 3 次，超时切 L2"),
        ("L2 断网", "端侧 0.5B LoRA 模型本地应答 + 本地 TTS 提示音", "仅白名单陪伴话术，禁止事实性回答"),
        ("L3 硬件降级", "端侧固定安抚话术 + 灯光情绪 + 记录待上传", "设备自检日志上报"),
    ]
    yy = 2078
    for a, b, c in rows:
        d.text((x + 40, yy), a, font=font(20, True), fill=(150, 96, 24))
        d.text((x + 260, yy), b, font=font(19), fill=INK)
        d.text((x + 1060, yy), c, font=font(19), fill=INK_SOFT)
        yy += 48

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "端云协同总体架构图.png")
    img.save(path, "PNG")
    return path


# ------------------------------------------------------- 端侧模型训练部署流水线
def build_pipeline() -> str:
    W, H = 3000, 1500
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    x = 70
    d.text((x, 46), "LoRA 微调模型 → 量化 → 端侧部署 → OTA 全链路流水线", font=font(48, True), fill=INK)
    d.line((x, 118, W - x, 118), fill=LINE, width=3)

    stages = [
        ("① 数据与训练", MODEL, [
            "语料：陪伴对话 + 人设台词 + 槽位问答",
            "去重/PII 脱敏/长度过滤 ≤512 token",
            "LLaMA-Factory / ms-swift SFT",
            "LoRA r=16 α=32 target q,k,v,o,gate,up,down",
            "产出：adapter_model.safetensors",
        ]),
        ("② 合并与量化", CLOUD, [
            "merge_lora → bf16 全量权重",
            "静态 INT8（PTQ）或 GGUF Q4_K_M",
            "端侧 INT8：逐层激活校准 512 条",
            "算子覆盖检查：ST Edge AI Core 支持表",
            "产出：merged.int8.bin / gguf / onnx",
        ]),
        ("③ 端侧编译", EDGE, [
            "ONNX 导出（dynamic axes 关闭）",
            "stedgeai generate / stm32ai optimize",
            "MCU：Ethos-U55 delegate + CMSIS-NN 兜底",
            "MPU：ExecuTorch / llama.cpp + NPU 后端",
            "产出：模型包 + 算子支持报告",
        ]),
        ("④ 烧录与推理", MEM, [
            "模型包入 OTA 差分区（A/B 双分区）",
            "MCU：外部 SPI NOR 32MB，映射 XIP",
            "MPU：DDR 加载，权重 mmap",
            "runtime：静态内存池 + 环形输入缓冲",
            "产出：可执行固件 + 模型清单",
        ]),
        ("⑤ 灰度与回滚", WARN, [
            "影子模式：新模型只打分不生效",
            "5% → 20% → 50% → 100% 分档",
            "指标：意图准确率 / 拒答率 / 崩溃率",
            "触发回滚：准确率掉 3pt 或崩溃 >0.5%",
            "产出：版本台账 + 回滚记录",
        ]),
    ]

    bw = 520
    gap = 42
    y = 170
    for i, (title, accent, bullets) in enumerate(stages):
        bx = x + i * (bw + gap)
        rect = (bx, y, bx + bw, y + 880)
        rounded(d, rect, 12, CARD, accent, 2)
        d.rounded_rectangle((bx, y, bx + bw, y + 62), radius=12, fill=accent)
        d.rectangle((bx, y + 40, bx + bw, y + 62), fill=accent)
        draw_centered(d, (bx + 6, y, bx + bw - 6, y + 62), title, font(25, True), (255, 255, 255))
        yy = y + 82
        for b in bullets:
            d.ellipse((bx + 24, yy + 7, bx + 34, yy + 17), fill=accent)
            for ln in wrap(d, b, font(18), bw - 80):
                d.text((bx + 46, yy), ln, font=font(18), fill=INK)
                yy += 27
            yy += 12
        if i < len(stages) - 1:
            arrow(d, (bx + bw + 4, y + 440), (bx + bw + gap - 6, y + 440), NEUTRAL, 4)

    band = (x, 1090, W - x, 1420)
    rounded(d, band, 12, (246, 251, 247), (170, 210, 190), 2)
    d.text((x + 26, 1106), "端侧模型准入门槛（任一不满足即不得下发设备）", font=font(26, True), fill=(0, 110, 80))
    rows = [
        ("权重体积", "MCU 档 ≤ 16MB（SPI NOR 32MB 分区）｜MPU 档 ≤ 900MB（DDR）"),
        ("RAM 占用", "MCU 档激活 + KV ≤ 2MB ｜ MPU 档 ≤ 1.2GB"),
        ("单次推理", "MCU ≤ 120ms ｜ MPU ≤ 250ms（首 token）"),
        ("算子覆盖", "100% 命中 NPU delegate；未命中算子数 = 0"),
        ("功耗", "MPU 档持续推理 ≤ 3.5W ｜ MCU 档 ≤ 1.2W"),
        ("回滚能力", "A/B 双分区 + 版本台账，5 分钟内可回退"),
    ]
    yy = 1152
    for a, b in rows:
        d.text((x + 40, yy), "· " + a, font=font(20, True), fill=(0, 110, 80))
        d.text((x + 300, yy), b, font=font(19), fill=INK)
        yy += 42

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "端侧模型训练部署流水线.png")
    img.save(path, "PNG")
    return path


# --------------------------------------------------- 记忆系统与千人千面架构图
def build_memory() -> str:
    W, H = 3000, 1900
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    x = 70
    w = W - 140
    d.text((x, 46), "记忆系统与千人千面：四层记忆 + 用户画像 + 偏好注入", font=font(48, True), fill=INK)
    d.line((x, 118, x + w, 118), fill=LINE, width=3)

    # 读路径
    d.text((x, 146), "读路径（每次轮次）", font=font(26, True), fill=MEM)
    read_cards = [
        ("① 触发", ["用户开口即触发", "wake / VAD 双触发"], MEM),
        ("② 查询生成", ["改写为独立检索式", "叠加画像关键词", "情感状态词加权"], MEM),
        ("③ 三路并行召回", ["短期：会话窗口 8 轮", "长期：Chroma 语义", "情景：相似事件"], MEM),
        ("④ 融合排序", ["RRF 融合 + 时序衰减", "作用域强制注入", "Top-K = 6"], MEM),
        ("⑤ 上下文装配", ["画像卡 + 记忆片段", "人设卡 + 风格卡", "预算 ≤ 1500 token"], MEM),
    ]
    cw, gap = 520, 36
    for i, (t, lines, accent) in enumerate(read_cards):
        bx = x + i * (cw + gap)
        rect = (bx, 196, bx + cw, 196 + 300)
        card(d, rect, t, lines, accent, 24, 18)
        if i < len(read_cards) - 1:
            arrow(d, (bx + cw + 2, 346), (bx + cw + gap - 4, 346), NEUTRAL, 3)

    # 四层记忆存储
    d.text((x, 540), "四层记忆存储", font=font(26, True), fill=MEM)
    layers = [
        ("短期记忆", "InMemoryMemory / AgentState", "会话内最近 8 轮原文", "进程内存 + 断点落盘", EDGE),
        ("工作记忆", "WorkingMemoryStore", "当前任务的中间态（槽位、待确认项）", "Redis + AgentState", CLOUD),
        ("长期记忆", "ChromaLongTermMemory", "用户事实、偏好、稳定画像事实", "Chroma 集合 mem_longterm", MEM),
        ("情景记忆", "EpisodicMemoryStore", "带情绪标签的历史互动事件", "PostgreSQL 事件表", MODEL),
    ]
    y = 590
    for name, impl, content, store, accent in layers:
        rect = (x, y, x + 1500, y + 150)
        rounded(d, rect, 10, CARD, accent, 2)
        d.text((rect[0] + 22, rect[1] + 16), name, font=font(24, True), fill=accent)
        d.text((rect[0] + 250, rect[1] + 18), impl, font=font(20), fill=INK)
        d.text((rect[0] + 250, rect[1] + 58), content, font=font(18), fill=INK_SOFT)
        d.text((rect[0] + 250, rect[1] + 96), "存储：" + store, font=font(18), fill=INK_SOFT)
        y += 170

    # 用户画像
    rect = (x + 1560, 590, x + w, 590 + 680)
    rounded(d, rect, 10, (250, 247, 240), (230, 200, 150), 2)
    d.text((rect[0] + 22, rect[1] + 16), "用户画像与偏好（千人千面来源）", font=font(24, True), fill=(150, 96, 24))
    profile = [
        ("静态属性", "年龄段 / 性别偏好 / 方言 / 称呼"),
        ("语言偏好", "语速 / 用词正式度 / 口头禅"),
        ("兴趣图谱", "话题权重 Top20，向量表示"),
        ("情绪基线", "基础情绪分布、压力敏感度"),
        ("交互偏好", "主动程度、话题发起频率、时段偏好"),
        ("禁忌与合规", "禁止话题、未成年人标记、监护人授权"),
        ("画像更新", "会话后异步抽取 + 置信度 + 衰减"),
    ]
    yy = rect[1] + 58
    for a, b in profile:
        d.text((rect[0] + 24, yy), "· " + a, font=font(19, True), fill=(150, 96, 24))
        d.text((rect[0] + 240, yy), b, font=font(18), fill=INK_SOFT)
        yy += 36
    d.text((rect[0] + 24, yy + 10), "画像 → 注入：人设语气 / 称呼 / 话题权重 / 长度偏好",
           font=font(19, True), fill=INK)

    # 写路径
    band = (x, 1320, x + w, 1820)
    rounded(d, band, 12, (250, 248, 253), CLOUD, 2)
    d.text((x + 26, 1340), "写路径（每轮结束后异步）", font=font(26, True), fill=CLOUD)
    write = [
        ("提取", ["LLM 结构化抽取", "事实 / 偏好 / 情绪 / 事件"], CLOUD),
        ("分类", ["写入哪一层记忆", "敏感信息判定"], CLOUD),
        ("写入", ["幂等键去重", "作用域强制绑定"], MEM),
        ("维护", ["去重归并", "时间衰减", "冲突消解"], MEM),
        ("优化", ["主动学习", "画像权重更新"], MODEL),
    ]
    cw2 = 540
    for i, (t, lines, accent) in enumerate(write):
        bx = x + 26 + i * (cw2 + 20)
        rect = (bx, 1390, bx + cw2, 1390 + 250)
        card(d, rect, t, lines, accent, 24, 18)
        if i < len(write) - 1:
            arrow(d, (bx + cw2 + 2, 1515), (bx + cw2 + 18, 1515), NEUTRAL, 3)
    d.text((x + 26, 1660), "去重", font=font(19), fill=INK_SOFT)
    d.text((x + 110, 1660), "：幂等键 = hash(用户ID + 语义指纹)，重复写入不产生新条目", font=font(18), fill=INK_SOFT)
    d.text((x + 26, 1696), "衰减", font=font(19), fill=INK_SOFT)
    d.text((x + 110, 1696), "：长期记忆按 30 天半衰期加权，长期未触达条目降权；被新事实覆盖则归档不删除", font=font(18), fill=INK_SOFT)
    d.text((x + 26, 1732), "隔离", font=font(19), fill=INK_SOFT)
    d.text((x + 110, 1732), "：ScopeResolver 在存储实现内部强制附加 tenantId + userId，调用方无法跨用户读取", font=font(18), fill=INK_SOFT)

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "记忆与千人千面架构图.png")
    img.save(path, "PNG")
    return path


# ------------------------------------------------------------ 实时会话时序图
def build_sequence() -> str:
    W, H = 3000, 1560
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    x = 70
    d.text((x, 46), "实时语音会话时序（含打断 barge-in 与首包延迟预算）", font=font(44, True), fill=INK)
    d.line((x, 112, x + W - 140, 112), fill=LINE, width=3)

    lanes = [
        ("用户", EDGE),
        ("端侧 STM32N6", EDGE),
        ("接入层 / MQTT", CLOUD),
        ("云端服务群", CLOUD),
        ("AgentScope 多智能体", MEM),
        ("TTS 服务", MODEL),
    ]
    lane_x, lane_w = 150, 420
    top = 160
    for i, (name, color) in enumerate(lanes):
        lx = lane_x + i * lane_w
        d.rounded_rectangle((lx, top, lx + 330, top + 56), radius=10, fill=color)
        draw_centered(d, (lx + 6, top, lx + 324, top + 56), name, font(21, True), (255, 255, 255))
        d.line((lx + 165, top + 56, lx + 165, H - 360), fill=(232, 238, 244), width=2)

    steps = [
        (0, 1, "说话：VAD 触发"),
        (1, 2, "PCM 流式分片上行（16k，20ms/片）"),
        (2, 3, "端侧 ASR / 或云端 ASR 兜底"),
        (3, 1, "文本 + 置信度回传"),
        (1, 3, "意图初判（规则+小模型）"),
        (3, 4, "AgentScope 主 Agent 路由"),
        (4, 3, "记忆召回 + 画像装配"),
        (4, 5, "TTS 首包请求（带音色+情感标签）"),
        (5, 1, "流式 PCM 下行"),
        (1, 0, "播放（同时输出情绪灯光）"),
    ]
    y = top + 90
    for src, dst, label in steps:
        sx = lane_x + src * lane_w + 165
        dx = lane_x + dst * lane_w + 165
        color = lanes[src][1]
        if abs(src - dst) == 1:
            arrow(d, (sx, y), (dx, y), color, 3)
        else:
            d.arc((min(sx, dx) - 70, y - 36, max(sx, dx) + 70, y + 36), start=0, end=180, fill=color, width=3)
            d.polygon([(dx, y), (dx - 12, y - 7), (dx + 12, y - 7)], fill=color)
        tx = (sx + dx) / 2
        tw = d.textlength(label, font=font(17))
        d.rectangle((tx - tw / 2 - 5, y - 32, tx + tw / 2 + 5, y - 2), fill=BG)
        d.text((tx - tw / 2, y - 30), label, font=font(17), fill=INK_SOFT)
        y += 88

    band = (x, 1220, x + W - 140, 1500)
    rounded(d, band, 12, (246, 251, 247), (170, 210, 190), 2)
    d.text((x + 26, 1238), "首包延迟预算（用户停止说话 → 第一声播放）", font=font(25, True), fill=(0, 110, 80))
    rows = [
        ("端侧 VAD 断句判定", "120ms", "尾点静音 500ms 提前起播可省 200ms"),
        ("端侧 ASR 末字", "180ms", "流式增量解码，末字 60ms"),
        ("上行网络 + 接入", "40ms", "同城边缘节点"),
        ("意图判定（含澄清）", "150ms", "规则命中 20ms；LLM 判定 150ms"),
        ("Agent 编排 + 记忆召回", "260ms", "记忆并行召回 120ms + 生成 200ms"),
        ("TTS 首包", "380ms", "流式合成，情感标签预合成"),
        ("下行网络 + 播放缓冲", "90ms", "首包直发，不等全量"),
        ("合计（正常路径）", "1220ms", "P95 目标 ≤ 1.8s"),
        ("合计（端侧兜底 L2）", "420ms", "断网时端侧 0.5B 模型本地应答"),
    ]
    yy = 1282
    for a, b, c in rows:
        bold = a.startswith("合计")
        d.text((x + 40, yy), a, font=font(19, True if bold else False), fill=INK if bold else INK_SOFT)
        d.text((x + 620, yy), b, font=font(19, True if bold else False), fill=INK if bold else INK_SOFT)
        d.text((x + 840, yy), c, font=font(18), fill=INK_SOFT)
        yy += 30

    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, "实时语音会话时序图.png")
    img.save(path, "PNG")
    return path


if __name__ == "__main__":
    print(build_overview())
    print(build_pipeline())
    print(build_memory())
    print(build_sequence())
