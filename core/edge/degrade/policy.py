"""端侧降级档位策略。

降级档位必须由**端侧本地**判定，不能依赖云端心跳 —— 网络断开时收不到任何
云端消息，靠心跳判定降级的话，恰恰在最需要降级的场景下永远等不到降级。

两个关键规则：

1. **逐级下降、逐级回升**。从 OFFLINE 直接跳回 NORMAL 会让端侧在恢复瞬间
   把积压的音频一次性冲上云端，反而把刚恢复的链路再次压垮。
2. **成功与失败计数互斥重置**。任一次成功清零失败计数、任一次失败清零成功计数，
   否则网络抖动（成功失败交替）会让计数单向累积，把健康链路拖进降级。
"""

from __future__ import annotations

from enum import Enum


class DegradeLevel(Enum):
    """端侧降级档位。

    成员全大写，与协议 ``degrade-level.schema.json`` 的枚举值一一对应。
    """

    NORMAL = "NORMAL"
    DEGRADED_NETWORK = "DEGRADED_NETWORK"
    OFFLINE = "OFFLINE"
    MINIMAL = "MINIMAL"


# 档位从正常到最低的顺序，下降与回升都沿此序列进行。
DEGRADE_ORDER: tuple[DegradeLevel, ...] = (
    DegradeLevel.NORMAL,
    DegradeLevel.DEGRADED_NETWORK,
    DegradeLevel.OFFLINE,
    DegradeLevel.MINIMAL,
)

# 默认连续失败次数达到该值即降一档。
DEFAULT_FAILURE_THRESHOLD = 3

# 默认连续成功次数达到该值即升一档。
DEFAULT_RECOVERY_SUCCESS_THRESHOLD = 3


class DegradePolicy:
    """端侧降级档位的状态机。

    判定完全在本地进行，不发起任何网络请求。
    """

    def __init__(
        self,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        recovery_success_threshold: int = DEFAULT_RECOVERY_SUCCESS_THRESHOLD,
    ) -> None:
        """构造降级策略。

        @param failure_threshold 连续上行失败多少次降一档
        @param recovery_success_threshold 连续上行成功多少次升一档
        @throws ValueError 任一阈值非正时抛出
        """
        if failure_threshold <= 0 or recovery_success_threshold <= 0:
            raise ValueError("降级与回升阈值都必须为正数")
        self._failure_threshold = failure_threshold
        self._recovery_success_threshold = recovery_success_threshold
        self._level = DegradeLevel.NORMAL
        self._failure_count = 0
        self._success_count = 0

    def current(self) -> DegradeLevel:
        """查询当前档位。

        @return 当前档位
        """
        return self._level

    def record_uplink_failure(self) -> DegradeLevel:
        """记录一次上行失败。

        @return 变化后的档位
        """
        self._success_count = 0
        self._failure_count += 1
        if self._failure_count < self._failure_threshold:
            return self._level
        self._failure_count = 0
        return self._step_down()

    def record_uplink_success(self) -> DegradeLevel:
        """记录一次上行成功。

        @return 变化后的档位
        """
        self._failure_count = 0
        self._success_count += 1
        if self._success_count < self._recovery_success_threshold:
            return self._level
        self._success_count = 0
        return self._step_up()

    def record_model_failure(self) -> DegradeLevel:
        """记录端侧模型异常。

        模型不可用时其余档位已无意义（弱网档仍要用模型，离线档更是如此），
        因此直接落到最低档。

        @return 变化后的档位
        """
        self._failure_count = 0
        self._success_count = 0
        self._level = DegradeLevel.MINIMAL
        return self._level

    def record_heartbeat_timeout(self) -> DegradeLevel:
        """记录一次心跳超时。

        @return 变化后的档位
        """
        return self.record_uplink_failure()

    def _step_down(self) -> DegradeLevel:
        """下降一档。

        @return 变化后的档位
        """
        index = DEGRADE_ORDER.index(self._level)
        if index < len(DEGRADE_ORDER) - 1:
            self._level = DEGRADE_ORDER[index + 1]
        return self._level

    def _step_up(self) -> DegradeLevel:
        """上升一档。

        @return 变化后的档位
        """
        index = DEGRADE_ORDER.index(self._level)
        if index > 0:
            self._level = DEGRADE_ORDER[index - 1]
        return self._level
