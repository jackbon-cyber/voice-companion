"""端侧本地应答器。

把「话术库 / 本地模型」变成一次**可见的本地应答**。

三个职责：

1. **选情感桶** —— 判定用户表达的情感标签，决定从话术库的哪个桶取句。
2. **生成应答** —— 委托 {@code LocalDialogEngine} 生成文本。
3. **标记来源** —— 本地应答必须明确标记为本地产生。

第 3 条是硬要求：端侧本地生成的回复**不得伪装成云端结果**。
用户在离线时听到机器人的回话，若不知道那是本地兜底产生的，
就会以为"云端还在正常服务"，从而对服务可用性产生错误判断。
标记方式是在应答对象上带 ``source`` 字段而不是改写文本 ——
改写文本会污染语音合成的输入，也会被长度门禁误判。

事实性请求单独走一条路：端侧**不生成**任何事实内容，只给引导话术。
"""

from __future__ import annotations

from dataclasses import dataclass

from core.edge.dialog.emotion import DEFAULT_EMOTION, detect_emotion
from core.edge.dialog.engine import LocalDialogEngine
from core.edge.dialog.factual import FactualGuard, FactualGuardResult

# 本地应答的来源标识。任何非本地的来源都不使用这个值。
LOCAL_SOURCE = "LOCAL"

# 离线档位下，事实性请求的引导话术。
#
# 与 {@code core.edge.dialog.factual.FACTUAL_GUIDANCE_PHRASES} 的区别：
# 那套话术假设"能上云查"，离线时查不了，必须明说自己离线，
# 否则用户会一直等一个永远不会来的答案。
OFFLINE_FACTUAL_PHRASES: tuple[str, ...] = (
    "这个得联网才能查清楚，我现在连不上网络，等会儿再问你好吗？",
    "涉及具体事实的事我不凭印象说，等网络回来我再帮你确认。",
    "这个我得查过才敢讲，现在离线，等我连上网再说。",
)


@dataclass(frozen=True)
class LocalReply:
    """一次本地应答。

    ``source`` 恒为 {@code LOCAL_SOURCE}：本地应答不允许有别的来源，
    这样调用方一眼就能确认"这条不是云端发的"。
    """

    #: 回复正文。
    text: str

    #: 情感标签。与协议 ``text-reply.schema.json`` 的 emotion 枚举一致。
    emotion: str = DEFAULT_EMOTION

    #: 来源标识，恒为 ``LOCAL_SOURCE``。
    source: str = LOCAL_SOURCE

    #: 是否处于离线档位下产生的应答。
    offline: bool = False

    #: 是否为事实性请求的引导话术。
    factual_guard: bool = False

    @property
    def locally_produced(self) -> bool:
        """是否由端侧本地产生。

        @return 本地产生时为 True
        """
        return self.source == LOCAL_SOURCE


class LocalResponder:
    """端侧本地应答器。"""

    def __init__(
        self,
        engine: LocalDialogEngine,
        factual_guard: FactualGuard | None = None,
    ) -> None:
        """构造应答器。

        @param engine 本地对话引擎（话术库或本地模型）
        @param factual_guard 事实性守卫；为 None 时用默认守卫
        """
        self._engine = engine
        self._factual_guard = factual_guard or FactualGuard()

    def check_factual(self, text: str) -> FactualGuardResult:
        """检查文本是否属于事实性请求。

        @param text 用户文本
        @return 守卫处理结果
        """
        return self._factual_guard.check(text)

    def respond(self, text: str, offline: bool = False) -> LocalReply:
        """生成一次陪伴性本地应答。

        @param text 用户说的文本，用于判定情感桶
        @param offline 是否处于离线档位
        @return 本地应答
        """
        emotion = detect_emotion(text)
        reply_text = self._engine.generate(emotion, text)
        if not reply_text:
            # 引擎兜底也返回空时不能返回空回复：空回复会让用户以为设备坏了。
            reply_text = "我在的，你说。"
        return LocalReply(
            text=reply_text,
            emotion=emotion,
            offline=offline,
        )

    def respond_factual(self, text: str, offline: bool = False) -> LocalReply:
        """对事实性请求生成引导应答。

        引导话术**不含任何事实内容** —— 只说明"这件事需要联网查询"。
        离线时额外说明当前无法联网，避免用户等一个不会到来的答案。

        @param text 用户说的文本
        @param offline 是否处于离线档位
        @return 本地引导应答
        """
        if offline:
            index = len(text) % len(OFFLINE_FACTUAL_PHRASES)
            reply_text = OFFLINE_FACTUAL_PHRASES[index]
        else:
            guidance = self._factual_guard.check(text).guidance
            reply_text = guidance or "这个我得查一下才敢回答你。"
        return LocalReply(
            text=reply_text,
            emotion=DEFAULT_EMOTION,
            offline=offline,
            factual_guard=True,
        )
