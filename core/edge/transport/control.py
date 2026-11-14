"""端侧控制通道客户端。

控制通道走 MQTT，承载设备管理消息（状态上报、配置下发、画像增量、版本通知）。

与音频上行通道**分离**是刻意的：控制通道故障（Broker 断连、消息堆积）
不应该影响正在进行的语音对话。

画像增量有 8KB 上限：超限的增量**整条拒绝并记录日志**，不做截断 ——
截断后下发的画像是一个"看起来合法、实际残缺"的状态，云端后续基于它做的
推理会静默地偏掉，比直接报错更难排查。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from core.edge.degrade.policy import DegradeLevel

# 画像增量的大小上限（字节）。与协议 control-channel.schema.json 的 maximum 一致。
PROFILE_DELTA_MAX_BYTES = 8192

# 控制通道日志器。
LOGGER = logging.getLogger(__name__)

# 画像增量回调签名。
ProfileDeltaCallback = Callable[[bytes], Awaitable[None]]


class ControlChannel:
    """端侧控制通道客户端。"""

    def __init__(self, topic_prefix: str) -> None:
        """构造控制通道客户端。

        @param topic_prefix MQTT 主题前缀
        """
        self._topic_prefix = topic_prefix
        self._client = None
        self._profile_delta_callbacks: list[ProfileDeltaCallback] = []

    @property
    def topic_prefix(self) -> str:
        """主题前缀。

        @return 主题前缀
        """
        return self._topic_prefix

    def on_profile_delta(self, callback: ProfileDeltaCallback) -> None:
        """注册画像增量回调。

        @param callback 回调，参数为增量原始字节
        """
        self._profile_delta_callbacks.append(callback)

    async def connect(self, broker_host: str = "127.0.0.1", broker_port: int = 1883) -> None:
        """连接 MQTT Broker。

        连接失败只记录日志，不抛出：控制通道不可用时设备仍应能正常对话。

        @param broker_host Broker 地址
        @param broker_port Broker 端口
        """
        try:
            import paho.mqtt.client as mqtt

            client = mqtt.Client()
            client.connect(broker_host, broker_port, keepalive=60)
            client.loop_start()
            client.subscribe(f"{self._topic_prefix}/down")
            self._client = client
        except Exception as error:
            LOGGER.warning("控制通道连接失败，设备将仅依赖音频通道工作：%s", error)

    async def report_status(self, payload: dict) -> None:
        """上报设备状态。

        @param payload 状态载荷
        """
        await self._publish(f"{self._topic_prefix}/up/status", payload)

    async def report_metric(self, payload: dict) -> None:
        """上报分段耗时指标。

        @param payload 指标载荷
        """
        await self._publish(f"{self._topic_prefix}/up/metric", payload)

    async def report_fault(self, payload: dict) -> None:
        """上报故障。

        @param payload 故障载荷
        """
        await self._publish(f"{self._topic_prefix}/up/fault", payload)

    async def report_degrade_level(self, level: DegradeLevel, reason: str = "") -> None:
        """上报降级档位。

        @param level 当前档位
        @param reason 降级原因
        """
        await self._publish(
            f"{self._topic_prefix}/up/degrade",
            {"level": level.value, "reason": reason},
        )

    async def deliver_profile_delta(self, payload: bytes) -> None:
        """下发一条画像增量。

        超过上限的增量**整条拒绝**并记录日志，不做截断。

        @param payload 增量原始字节
        @return 是否已下发
        """
        if len(payload) > PROFILE_DELTA_MAX_BYTES:
            LOGGER.warning(
                "画像增量超过上限 %d 字节（实际 %d），已整条拒绝，未下发",
                PROFILE_DELTA_MAX_BYTES,
                len(payload),
            )
            return False
        for callback in self._profile_delta_callbacks:
            await callback(payload)
        return True

    async def close(self) -> None:
        """关闭控制通道。

        关闭失败只记录日志，不抛出。
        """
        if self._client is None:
            return
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception as error:
            LOGGER.warning("控制通道关闭失败：%s", error)
        finally:
            self._client = None

    async def _publish(self, topic: str, payload: dict) -> None:
        """发布一条消息。

        @param topic 主题
        @param payload 载荷
        """
        if self._client is None:
            LOGGER.warning("控制通道未连接，丢弃主题 %s 的消息", topic)
            return
        import json

        try:
            self._client.publish(topic, json.dumps(payload, ensure_ascii=False))
        except Exception as error:
            LOGGER.warning("控制通道发布失败，主题 %s：%s", topic, error)
