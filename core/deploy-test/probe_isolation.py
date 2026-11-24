"""部署实测：跨用户隔离（手册第 5 步的核心断言）。

**要验什么**

用户 A 说过"我妈妈叫李芳"，用户 B 从没说过这件事。
B 问"我妈妈叫什么"时，**不能引用 A 的记忆**。

**为什么这条最重要**

隔离失效是陪伴产品最严重的安全问题之一：
A 的家庭信息被念给 B 听，用户 A 完全不知情。
而且这类缺陷**只在真实部署下暴露** ——
本地跑的时候内存里就一个作用域，跨作用域的过滤路径可能压根没被走到。

**顺带验跨会话隔离**：同一用户开新会话，
记忆应当仍在（按 ownerKey 隔离，不按 sessionId 隔离）。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from websockets.asyncio.client import connect

HOST = "127.0.0.1"
UPLINK_PORT = 18080
TOKEN = "deploy-test-token-abc123"

FACT = "我妈妈叫李芳，她对芒果过敏"
KEYWORD = "李芳"


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
    deadline = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < deadline:
        remaining = deadline - asyncio.get_running_loop().time()
        raw = await asyncio.wait_for(socket.recv(), timeout=remaining)
        message = json.loads(raw)
        if message.get("text"):
            return message
    return None


async def _talk(owner: str, session_id: str, text: str, sequence: int = 0) -> dict[str, Any] | None:
    """建会话、发一句话、取回回复。

    @param owner 用户标识
    @param session_id 会话标识
    @param text 说的话
    @param sequence 序号
    @return 回复消息
    """
    headers = {"Authorization": f"Bearer {TOKEN}"}
    url = f"ws://{HOST}:{UPLINK_PORT}/voice/uplink"
    async with connect(url, additional_headers=headers, open_timeout=10) as socket:
        await socket.send(json.dumps(_begin(session_id, owner), ensure_ascii=False))
        await asyncio.sleep(0.4)
        await socket.send(json.dumps(_intent(session_id, text, sequence), ensure_ascii=False))
        return await _drain_until_reply(socket)


async def run() -> int:
    print("=== 部署实测：跨用户隔离 ===")
    print()

    user_a = "deploy-iso-a"
    user_b = "deploy-iso-b"

    # A 说出事实
    a_reply = await _talk(user_a, "iso-a-s1", FACT)
    print(f"① A 说：{FACT}")
    print(f"   A 的回复：{a_reply.get('text') if a_reply else '（无回复）'}")
    a_citations = a_reply.get("citations") if a_reply else None
    print(f"   A 的引用：{a_citations}")
    print()

    # B 问同样的事 —— 不该引用 A 的记忆
    b_reply = await _talk(user_b, "iso-b-s1", "我妈妈叫什么？")
    print(f"② B 问：我妈妈叫什么？")
    print(f"   B 的回复：{b_reply.get('text') if b_reply else '（无回复）'}")
    b_citations = b_reply.get("citations") if b_reply else None
    print(f"   B 的引用：{b_citations}")
    print()

    # B 换个说法再问一次 —— 防止"只是这次没命中"的侥幸
    b_reply2 = await _talk(user_b, "iso-b-s2", "我妈妈对芒果过敏吗？")
    print(f"③ B 再问：我妈妈对芒果过敏吗？")
    print(f"   B 的回复：{b_reply2.get('text') if b_reply2 else '（无回复）'}")
    b_citations2 = b_reply2.get("citations") if b_reply2 else None
    print(f"   B 的引用：{b_citations2}")
    print()

    # A 换新会话再问 —— 按 ownerKey 隔离，应当仍能召回
    a_reply2 = await _talk(user_a, "iso-a-s2", "我妈妈对芒果过敏吗？")
    print(f"④ A 换新会话再问：我妈妈对芒果过敏吗？")
    print(f"   A 的回复：{a_reply2.get('text') if a_reply2 else '（无回复）'}")
    a_citations2 = a_reply2.get("citations") if a_reply2 else None
    print(f"   A 的引用：{a_citations2}")
    print()

    print("=== 判定 ===")
    ok = True

    if not a_citations:
        print("★ A 自己的记忆没召回 —— 记忆功能本身不通")
        ok = False
    else:
        print("✓ A 能召回自己的记忆")

    if b_citations:
        print(f"★ B 引用到了记忆（{b_citations}）—— 跨用户隔离失效")
        ok = False
    else:
        print("✓ B 没有引用任何记忆 —— 跨用户隔离生效")

    if b_citations2:
        print(f"★ B 换个说法又引用到了（{b_citations2}）—— 隔离失效")
        ok = False
    else:
        print("✓ B 换说法仍无引用 —— 隔离不是侥幸")

    if b_reply and KEYWORD in (b_reply.get("text") or ""):
        print(f"★ B 的回复里出现了 A 的事实「{KEYWORD}」—— 泄漏")
        ok = False
    else:
        print(f"✓ B 的回复里没有 A 的事实")

    if a_citations2:
        print("✓ A 换会话仍能召回 —— 隔离按 ownerKey 而非 sessionId")
    else:
        print("★ A 换会话就召不回了 —— 隔离粒度不对")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
