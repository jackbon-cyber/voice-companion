"""端侧情感标签判定。

话术库按情感标签分桶（``core/edge/dialog/phrases.py``），但**谁来决定用哪个桶**
是个容易被忽略的缺口：没有这一步，话术库只能永远取默认桶，"情绪回应"名存实亡。

判定刻意用**关键词表**而不是模型：

- 端侧要在没有模型、甚至没有网络的机器上工作，关键词表零依赖、零延迟；
- 情感判定的容错度较高 —— 判错一桶的后果只是话术语气略偏，
  而事实性判定判错会导致编造，容错度完全不同；
- 匹配时取**最长命中关键词**所在桶：长词更具体。
  "今天不开心" 命中 "不开心"（sadness），
  "今天不开心，但刚才那个笑话真的很好笑" 同时命中 "笑话"（joy）与 "不开心"，
  取最长词会落到 sadness —— 这里存在固有歧义，
  但"先取更长词"比"先取字典序"更可预期。

新增情绪类型只需往表里加一条，不改动判定逻辑。
"""

from __future__ import annotations

# 情感标签全集。与协议 ``text-reply.schema.json`` 的 emotion 枚举一一对应。
EMOTION_TAGS: tuple[str, ...] = (
    "neutral",
    "joy",
    "sadness",
    "anger",
    "fear",
    "surprise",
    "tenderness",
    "encouragement",
)

# 无情感线索时使用的标签。
DEFAULT_EMOTION = "neutral"

# 情感关键词表。键为情感标签，值为候选关键词。
#
# 只用**两字及以上**的高区分度词。像"喜""怒"这类单字会命中
# "喜欢""遇见"等无关表达，把情绪判反比判成 neutral 更伤体验。
EMOTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "joy": (
        "开心",
        "高兴",
        "太好了",
        "真棒",
        "真好",
        "哈哈",
        "顺利",
        "好消息",
        "升职",
        "成功了",
        "通过了考试",
    ),
    "sadness": (
        "难过",
        "伤心",
        "想哭",
        "失落",
        "委屈",
        "不开心",
        "很低落",
        "沮丧",
        "白忙了",
    ),
    "anger": (
        "生气",
        "气死",
        "烦死",
        "烦人",
        "讨厌",
        "恼火",
        "火大",
        "忍不了",
    ),
    "fear": (
        "害怕",
        "担心",
        "紧张",
        "恐惧",
        "不安",
        "焦虑",
        "好怕",
    ),
    "surprise": (
        "没想到",
        "居然",
        "竟然",
        "突然",
        "惊讶",
        "天啊",
        "不会吧",
    ),
    "tenderness": (
        "喜欢你",
        "想你了",
        "抱抱",
        "陪我",
        "爱你",
        "好想你",
        "想见你",
    ),
    "encouragement": (
        "加油",
        "坚持",
        "努力",
        "别放弃",
        "你可以的",
        "我相信你",
        "再试试",
    ),
}


def detect_emotion(text: str) -> str:
    """判定一段文本的情感标签。

    @param text 用户文本
    @return 情感标签；无线索或未命中任何关键词时返回 ``neutral``
    """
    if not text:
        return DEFAULT_EMOTION

    best_tag = DEFAULT_EMOTION
    best_keyword = ""
    for tag, keywords in EMOTION_KEYWORDS.items():
        for keyword in keywords:
            if keyword not in text:
                continue
            if len(keyword) > len(best_keyword):
                best_tag = tag
                best_keyword = keyword
    return best_tag
