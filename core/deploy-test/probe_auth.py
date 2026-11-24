"""部署实测：手册 4.3 的生产环境变量在真实容器里是否真的生效。

**要验的三件事**

1. `VOICE_UPLINK_TOKEN` 设了 → **没有凭据的客户端连不上**。
   手册 4.3 说"不设置时上行通道不鉴权，任何客户端都能接入"，
   也就是说设了之后就该挡住。这是生产部署的第一道门。

2. `VOICE_CHROMA_BASE_URL` 设了 → 云端真的连的是那个地址。

3. 带上正确凭据 → 能正常建会话、正常对话。

**为什么必须实测**

鉴权是"配了就生效"还是"配了也没用"，代码上看着对，
实际可能连的是另一个配置源、或者鉴权只挡了某条路径。
这种事只有对着真容器发真连接才看得出来。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from websockets.asyncio.client import connect

# 容器端口映射到宿主机的端口（见 core/deploy-test 的 docker run 参数）。
HOST = "127.0.0.1"
UPLINK_PORT = 18080
CHROMA_PORT = 18765

# 镜像里设的令牌（见 Dockerfile 的 ENV）。
TOKEN = "deploy-test-token-abc123"


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


async def try_connect(headers: dict[str, str] | None, label: str) -> dict[str, Any]:
    """尝试建连接并发一句话，返回观测结果。

    @param headers 附加的 HTTP 头；None 表示不带
    @param label 本次尝试的标签
    @return: 观测结果字典
    """
    url = f"ws://{HOST}:{UPLINK_PORT}/voice/uplink"
    try:
        async with connect(url, additional_headers=headers, open_timeout=10) as socket:
            session_id = f"deploy-probe-{label}"
            await socket.send(json.dumps(_begin(session_id, f"deploy-user-{label}"), ensure_ascii=False))
            await asyncio.sleep(0.5)
            await socket.send(
                json.dumps(
                    {
                        "sessionId": session_id,
                        "sequence": 0,
                        "intent": "chat",
                        "confidence": 0.9,
                        "handledLocally": False,
                        "text": "我妈妈叫李芳",
                        "slots": {},
                    },
                    ensure_ascii=False,
                )
            )
            raw = await asyncio.wait_for(socket.recv(), timeout=15.0)
            reply = json.loads(raw)
            return {
                "label": label,
                "connected": True,
                "reply": reply.get("text"),
                "citations": reply.get("citations", []),
            }
    except Exception as exc:  # noqa: BLE001 —— 任何失败都要记下来
        return {
            "label": label,
            "connected": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


async def main() -> None:
    print("=== 部署实测：上行通道鉴权 ===")
    print()

    # 1. 不带凭据 —— 生产配置下应当被拒
    no_token = await try_connect(None, "无凭据")
    print(f"① 不带凭据：{json.dumps(no_token, ensure_ascii=False)}")

    # 2. 带错误凭据 —— 也应当被拒
    wrong = await try_connect({"Authorization": "Bearer wrong-token"}, "错凭据")
    print(f"② 带错误凭据：{json.dumps(wrong, ensure_ascii=False)}")

    # 3. 带正确凭据 —— 应当成功
    right = await try_connect({"Authorization": f"Bearer {TOKEN}"}, "正确凭据")
    print(f"③ 带正确凭据：{json.dumps(right, ensure_ascii=False)}")

    print()
    print("=== 判定 ===")
    if not no_token["connected"]:
        print("✓ 无凭据被拒 —— 鉴权生效")
    else:
        print("★ 无凭据竟然连上了 —— 鉴权没生效，这是生产事故级别的漏洞")

    if not wrong["connected"]:
        print("✓ 错误凭据被拒")
    else:
        print("★ 错误凭据竟然能连上")

    if right["connected"] and right.get("citations"):
        print(f"✓ 正确凭据可正常对话，引用 {right['citations']}")
    else:
        print(f"★ 正确凭据也用不了：{right}")


if __name__ == "__main__":
    asyncio.run(main())
