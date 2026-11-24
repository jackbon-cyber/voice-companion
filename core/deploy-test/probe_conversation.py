"""部署实测：完整对话链路（记忆写入 → 召回 → 引用）。

这是"第四步部署"的核心验收项。前面已经验过：
  * 鉴权生效（无凭据 401）
  * 协议 schema 在 jar 内可用（不再"未知协议 schema"）
  * 三个服务按手册顺序起来

这一步验的是**功能**：容器里说一句话 → 云端记住 → 再问时能召回并引用。

**为什么必须实测**

"服务起得来"和"服务能用"是两件事。之前那次部署里，
协议 schema 全丢、嵌入服务没起，云端照样返回 200 和一句降级话术，
看起来一切正常 —— 实际协议校验从未生效、记忆从未写入。

所以这里断言的是**引用来源**，不是"有回复就算过"。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from websockets.asyncio.client import connect

HOST = "127.0.0.1"
UPLINK_PORT = 18080
TOKEN = "deploy-test-token-abc123"

# 记忆内容里放一个独特的词，用来验证"引用的是真的这条记忆"，
# 而不是碰巧召回了一条别的。
FACT = "我妈妈叫李芳，她对芒果过敏"
FACT_KEYWORD = "芒果过敏"


def _begin(session_id: str, owner_key: str) -> dict[str, Any]:
    return {
        "sessionId": session_id,
        "type": "begin",
        "ownerKey": owner_key,
        "timestampMs": 0,
        "audioFormat": {
            "sampleRate": 16000,
            "channels": 1,
            "bitDepth": 16,
            "encoding": "PCM_S16LE",
            "frameDurationMs": 20,
        },
    }


def _intent(session_id: str, text: str, sequence: int = 0) -> dict[str, Any]:
    return {
        "sessionId": session_id,
        "sequence": sequence,
        "intent": "chat",
        "confidence": 0.9,
        "handledLocally": False,
        "text": text,
        "slots": {},
    }


async def _drain_until_reply(socket: Any, timeout: float = 25.0) -> dict[str, Any] | None:
    """收到一条带文本回复的消息就返回。

    @param socket 已连接的 WebSocket
    @param timeout 超时秒数
    @return 回复消息；超时返回 None
    """
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        remaining = deadline - asyncio.get_running_loop().time()
        raw = await asyncio.wait_for(socket.recv(), timeout=remaining)
        message = json.loads(raw)
        if message.get("text"):
            return message
    return None


async def run() -> int:
    print("=== 部署实测：完整对话链路 ===")
    print()

    headers = {"Authorization": f"Bearer {TOKEN}"}
    url = f"ws://{HOST}:{UPLINK_PORT}/voice/uplink"
    owner = "deploy-user-full"
    session_id = "deploy-full-1"

    async with connect(url, additional_headers=headers, open_timeout=10) as socket:
        await socket.send(json.dumps(_begin(session_id, owner), ensure_ascii=False))
        await asyncio.sleep(0.5)

        # 第一轮：陈述事实，等云端写入记忆
        await socket.send(json.dumps(_intent(session_id, FACT), ensure_ascii=False))
        first = await _drain_until_reply(socket)
        print(f"① 陈述事实后的回复：{first.get('text') if first else '（无回复）'}")
        print(f"   引用：{first.get('citations') if first else '—'}")

        # 第二轮：问相关问题，期望召回刚才那条记忆
        await socket.send(
            json.dumps(_intent(session_id, "我妈妈对什么过敏？", sequence=1), ensure_ascii=False)
        )
        second = await _drain_until_reply(socket)
        print(f"② 提问后的回复：{second.get('text') if second else '（无回复）'}")
        citations = second.get("citations") if second else None
        print(f"   引用：{citations}")

        print()
        print("=== 判定 ===")
        ok = True

        if second is None:
            print("★ 第二轮没有回复 —— 对话链路不通")
            return 1

        if not citations:
            print("★ 没有引用 —— 记忆没写入，或召回失败")
            ok = False
        else:
            print(f"✓ 有引用（{len(citations)} 条）")

        reply_text = second.get("text") or ""
        if FACT_KEYWORD in reply_text:
            print(f"✓ 回复命中记忆关键词「{FACT_KEYWORD}」")
        else:
            print(f"★ 回复里没有「{FACT_KEYWORD}」：{reply_text}")
            ok = False

        return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
