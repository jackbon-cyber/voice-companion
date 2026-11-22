"""端侧意图两级判定。

两级：

1. **规则表** —— 命中高频固定意图，本地直接执行，不上云。
2. **小模型** —— 覆盖规则表管不着的长尾表达，判定结果仍**上云执行**
   （端侧只负责分类，不负责执行长尾意图）。

规则命中但识别置信度低时**降级为关键词匹配**：ASR 认错了字，但关键词
往往还在（"把音量调到五十" 被认成 "把音亮调到五十"，规则仍能命中），
此时按关键词执行是安全的。若连关键词都没命中，则**拒识**——不上云，
等用户下一句。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from core.edge.intent.rules import DEFAULT_RULES, IntentRule

# 未知意图标识。
UNKNOWN_INTENT = "unknown"

# 小模型判定的置信度下限。低于该值认为模型也没把握，交给云端。
MODEL_CONFIDENCE_THRESHOLD = 0.6

# 识别结果可用的置信度下限。低于该值只能靠关键词匹配。
#
# **与固件的一致性**：固件侧 `vc_intent_task.h` 的
# `VC_INTENT_KEYWORD_ONLY_THRESHOLD` 必须与本值一致（千分比 500）。
# 两者不一致时，同一句话在固件上按关键词执行、在模拟端却拒识 ——
# 开发者以为的行为与真机不一致。
# 由 core/tests/device_ref/test_behavior_contract.py 守着。
RECOGNITION_CONFIDENCE_THRESHOLD = 0.5

# 关键词匹配的置信度。识别本身不可信时，关键词命中也不给高置信度。
KEYWORD_CONFIDENCE = 0.7


@runtime_checkable
class LocalIntentModel(Protocol):
    """端侧意图小模型契约。"""

    def classify(self, text: str) -> tuple[str, float]:
        """判定一段文本的意图。

        @param text 用户文本
        @return (意图标识, 置信度)
        """
        ...


@dataclass(frozen=True)
class IntentDecision:
    """一次意图判定的结果。"""

    intent: str
    confidence: float
    slots: dict[str, str] = field(default_factory=dict)
    handled_locally: bool = False


class IntentDetector:
    """规则表 + 小模型的两级意图判定器。"""

    def __init__(
        self,
        rules: tuple[IntentRule, ...] = DEFAULT_RULES,
        local_model: LocalIntentModel | None = None,
    ) -> None:
        """构造判定器。

        @param rules 规则表
        @param local_model 端侧小模型，可为 None（只走规则）
        """
        self._rules = rules
        self._local_model = local_model

    def detect(self, text: str, confidence: float) -> IntentDecision:
        """判定一段文本的意图。

        @param text 用户文本
        @param confidence ASR 给出的置信度
        @return 判定结果
        """
        matched = self._match_rules(text)

        if matched is not None:
            # 识别可信时给规则本身的置信度；识别不可信时降级为关键词匹配，
            # 置信度相应下调，避免上层误以为是高置信度的确定判定。
            rule_confidence = (
                matched.confidence
                if confidence >= RECOGNITION_CONFIDENCE_THRESHOLD
                else KEYWORD_CONFIDENCE
            )
            return IntentDecision(
                intent=matched.intent,
                confidence=rule_confidence,
                slots=dict(matched.slots),
                handled_locally=True,
            )

        if self._local_model is not None:
            intent, model_confidence = self._local_model.classify(text)
            if intent and intent != UNKNOWN_INTENT and model_confidence >= MODEL_CONFIDENCE_THRESHOLD:
                # 长尾意图由端侧分类，但**上云执行**。
                return IntentDecision(
                    intent=intent,
                    confidence=model_confidence,
                    slots={},
                    handled_locally=False,
                )

        return IntentDecision(intent=UNKNOWN_INTENT, confidence=confidence, handled_locally=False)

    def _match_rules(self, text: str) -> IntentRule | None:
        """在规则表里找一条命中的规则。

        @param text 用户文本
        @return 命中的规则；未命中返回 None
        """
        if not text:
            return None
        for rule in self._rules:
            for keyword in rule.keywords:
                if keyword in text:
                    return rule
        return None
