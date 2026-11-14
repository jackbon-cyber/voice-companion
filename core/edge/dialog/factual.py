"""端侧事实性请求回绝。

陪伴机器人的最大风险是**编造**：用户问"我上次体检的血压是多少"，
机器人随口说"120/80"——用户会当成真事。

处理原则是**引导上云，而不是编造**：

- 端侧**不生成**任何具体的人名、地名、日期、数字事实；
- 识别到事实性请求时，返回一个明确的"该上云"信号，由云端检索记忆后回答；
- 端侧如果必须回应，给的是**不含事实内容**的引导话术。

这里刻意做成**规则表 + 分类函数**而不是一个大 if：事实性请求的类型会不断增加
（天气、股价、药品剂量、路况、彩票……），每加一类就要改判定逻辑 ——
用规则表则只需追加一条。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# 事实性请求的分类。
class FactualCategory(Enum):
    """事实性请求的类别。"""

    #: 涉及具体人名、关系、过往事件。
    PERSONAL_FACT = "PERSONAL_FACT"
    #: 涉及具体地点、场所、路线。
    LOCATION_FACT = "LOCATION_FACT"
    #: 涉及具体日期、时间点。
    TIME_FACT = "TIME_FACT"
    #: 涉及具体数值（行情、剂量、统计）。
    NUMERIC_FACT = "NUMERIC_FACT"
    #: 涉及外部实时信息（天气、新闻、股价）。
    REALTIME_FACT = "REALTIME_FACT"


# 事实性请求的关键词表。命中任一即视为该类事实性请求。
# 刻意只用**高区分度**的词：像"多少钱""几点"这类词太泛，
# 命中它们会把大量闲聊误判成事实性请求。
FACTUAL_KEYWORDS: dict[FactualCategory, tuple[str, ...]] = {
    FactualCategory.PERSONAL_FACT: (
        "上次",
        "之前",
        "我说过",
        "我告诉过你",
        "还记得",
        "叫什么名字",
        "是谁",
    ),
    FactualCategory.LOCATION_FACT: (
        "在哪里",
        "在哪儿",
        "地址是",
        "怎么走",
        "路线",
    ),
    FactualCategory.TIME_FACT: (
        "哪一天",
        "几号",
        "什么时候",
        "多久之前",
    ),
    FactualCategory.NUMERIC_FACT: (
        "多少钱",
        "剂量",
        "毫克",
        "血压",
        "多少度",
        "涨了多少",
        "跌了多少",
    ),
    FactualCategory.REALTIME_FACT: (
        "天气",
        "气温",
        "新闻",
        "股价",
        "汇率",
        "路况",
    ),
}

# 端侧的引导话术。**不含任何事实内容** —— 只说明"这件事要去查"。
FACTUAL_GUIDANCE_PHRASES: tuple[str, ...] = (
    "这个我得查一下才敢回答你，稍等哦。",
    "涉及具体数字的事我不乱说，让我查过再讲。",
    "这类事情我不想凭印象编，我去确认一下。",
)


@dataclass(frozen=True)
class FactualRequest:
    """一次事实性请求的识别结果。

    ``category`` 为 None 表示不是事实性请求。
    """

    #: 命中的类别；不是事实性请求时为 None。
    category: FactualCategory | None = None
    #: 命中的关键词；不是事实性请求时为空。
    matched_keyword: str = ""
    #: 用户原始文本。
    text: str = ""

    @property
    def is_factual(self) -> bool:
        """是否为事实性请求。

        @return 是事实性请求时为 True
        """
        return self.category is not None


class FactualRequestDetector:
    """事实性请求识别器。"""

    def __init__(
        self,
        keyword_table: dict[FactualCategory, tuple[str, ...]] | None = None,
    ) -> None:
        """构造识别器。

        @param keyword_table 关键词表；为 None 时用默认表
        """
        self._keyword_table = keyword_table or FACTUAL_KEYWORDS

    def detect(self, text: str) -> FactualRequest:
        """识别一段文本是否属于事实性请求。

        一句话可能同时命中多类（"我上次的血压是多少"既是个人事实也是数值事实）。
        判定时取**最长命中关键词**所在类别 —— 关键词越长说明请求越具体，
        分类越准；靠字典顺序决定会让结果依赖无关的类别排列顺序。

        @param text 用户文本
        @return 识别结果
        """
        if not text:
            return FactualRequest(text=text)

        best_category: FactualCategory | None = None
        best_keyword = ""
        for category, keywords in self._keyword_table.items():
            for keyword in keywords:
                if keyword not in text:
                    continue
                if len(keyword) > len(best_keyword):
                    best_category = category
                    best_keyword = keyword

        if best_category is None:
            return FactualRequest(text=text)
        return FactualRequest(
            category=best_category,
            matched_keyword=best_keyword,
            text=text,
        )

    def guidance_phrase(self, request: FactualRequest) -> str | None:
        """取引导话术。

        @param request 事实性请求识别结果
        @return 引导话术；不是事实性请求时为 None
        """
        if not request.is_factual:
            return None
        # 按关键词长度降序选话术：命中词越长说明请求越具体，越需要谨慎回应。
        index = len(request.matched_keyword) % len(FACTUAL_GUIDANCE_PHRASES)
        return FACTUAL_GUIDANCE_PHRASES[index]


@dataclass
class FactualGuardResult:
    """事实性守卫的处理结果。"""

    #: 是否应当上云求证。
    should_go_to_cloud: bool = False
    #: 端侧可直接给出的引导话术；没有时为 None。
    guidance: str | None = None
    #: 命中的事实性类别；不是事实性请求时为 None。
    category: FactualCategory | None = None
    #: 附带说明。
    notes: list[str] = field(default_factory=list)


class FactualGuard:
    """端侧事实性守卫。

    把"识别事实性请求"与"决定怎么办"合成一步，供对话引擎调用。
    """

    def __init__(self, detector: FactualRequestDetector | None = None) -> None:
        """构造守卫。

        @param detector 识别器；为 None 时用默认识别器
        """
        self._detector = detector or FactualRequestDetector()

    def check(self, text: str) -> FactualGuardResult:
        """检查一段用户文本。

        @param text 用户文本
        @return 处理结果
        """
        request = self._detector.detect(text)
        if not request.is_factual:
            return FactualGuardResult()

        notes = [f"命中事实性请求：{request.category.value}（关键词：{request.matched_keyword}）"]
        return FactualGuardResult(
            should_go_to_cloud=True,
            guidance=self._detector.guidance_phrase(request),
            category=request.category,
            notes=notes,
        )
