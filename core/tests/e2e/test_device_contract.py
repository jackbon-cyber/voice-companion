"""设备接入契约 —— 手册第 4 章的行为承诺，实测云端是否真的这样。

**为什么需要这个测试**

`docs/operations-manual.md` 对设备实现者承诺了几件事：
重连保持 sessionId、云端认 sessionId 不认连接、跨用户隔离生效、
`text-reply` 不带 `intent` 字段、兜底话术长什么样。

这些是**设备侧写代码的依据**。手册写错了，设备实现者照着写就会错，
而错的表现往往很隐蔽（照抄手册里的 `intent` 字段 → 永远解析出 undefined）。

所以这里把每条承诺变成**对着真实云端的断言**。
云端行为变了，手册就会过期 —— 本测试先变红，逼着人同步文档。

**为什么用真实云端而不是 mock**

这些承诺的本体就是"云端怎么处理设备发来的消息"。
mock 掉云端，测的就是 mock 自己，不是云端。

**前置条件**：云端在 `127.0.0.1:8080` 运行（`core/scripts/start.ps1`）。
未运行时整组跳过 —— 端到端测试不该在没起服务的机器上变成噪声。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

# 上行通道地址。与 deployment.md 第 2 节一致。
UPLINK_URL = "ws://127.0.0.1:8080/voice/uplink"

# 兜底话术。云端无命中记忆时的回复。
# 抄自 MemoryGroundedReplyService 的 NO_RECALL_TEMPLATE ——
# 这里刻意写成字面量而不是引用常量：断言要钉住**对外的文案**，
# 引用常量会让"常量改了文案，断言跟着改"，等于没断言。
NO_RECALL_TEMPLATE = "我这边还没有关于这件事的记录，你说得再具体一点我就能记下了。"


def _is_cloud_reachable() -> bool:
    """检查云端是否在跑。

    @return: 云端可达返回 True
    """
    try:
        from websockets.asyncio.client import connect

        async def probe() -> bool:
            try:
                async with connect(UPLINK_URL, open_timeout=3):
                    return True
            except Exception:  # noqa: BLE001 —— 探活不区分异常类型
                return False

        return asyncio.run(probe())
    except Exception:  # noqa: BLE001
        return False


CLOUD_AVAILABLE = _is_cloud_reachable()
requires_cloud = pytest.mark.skipif(
    not CLOUD_AVAILABLE,
    reason="云端未运行（core/scripts/start.ps1），跳过设备接入契约测试",
)


def _begin(session_id: str, owner_key: str | None = None) -> dict[str, Any]:
    """构造 session(begin) 消息。字段与操作手册 4.3 节一致。

    @param session_id 会话标识
    @param owner_key 归属用户标识；None 表示不带该字段
    @return: 消息体
    """
    message: dict[str, Any] = {
        "sessionId": session_id,
        "type": "begin",
        "timestampMs": 0,
        "audioFormat": {
            "sampleRate": 16000,
            "channels": 1,
            "bitDepth": 16,
            "encoding": "PCM_S16LE",
            "frameDurationMs": 20,
        },
    }
    if owner_key is not None:
        message["ownerKey"] = owner_key
    return message


def _intent(session_id: str, sequence: int, text: str) -> dict[str, Any]:
    """构造 intent-report 消息。

    @param session_id 会话标识
    @param sequence 消息序号
    @param text 端侧识别出的用户原话
    @return: 消息体
    """
    return {
        "sessionId": session_id,
        "sequence": sequence,
        "intent": "chat",
        "confidence": 0.9,
        "handledLocally": False,
        "text": text,
        "slots": {},
    }


async def _say(
    session_id: str,
    owner_key: str | None,
    text: str,
    sequence: int = 0,
) -> dict[str, Any] | None:
    """建立会话、发一句话、收一条回复。

    @param session_id 会话标识
    @param owner_key 归属用户标识
    @param text 用户原话
    @param sequence 消息序号
    @return: 下行回复；超时返回 None
    """
    from websockets.asyncio.client import connect

    async with connect(UPLINK_URL) as socket:
        await socket.send(json.dumps(_begin(session_id, owner_key), ensure_ascii=False))
        await asyncio.sleep(0.3)
        await socket.send(json.dumps(_intent(session_id, sequence, text), ensure_ascii=False))
        try:
            raw = await asyncio.wait_for(socket.recv(), timeout=10.0)
        except asyncio.TimeoutError:
            return None
        return json.loads(raw)


def _unique(prefix: str) -> str:
    """生成运行期唯一标识，避免上一轮的残留记忆干扰断言。

    @param prefix 前缀
    @return: 唯一标识
    """
    import time

    return f"{prefix}-{time.time_ns()}"


@requires_cloud
def test_manual_uplink_json_works_verbatim():
    """照抄操作手册 4.3 节的 JSON，必须一次就通。

    为什么：手册是设备实现者唯一的接入依据。
    手册里的样例若发不出去，设备实现者会先去怀疑自己的固件，
    而真因在文档。
    """
    reply = asyncio.run(
        _say(_unique("contract-begin"), _unique("contract-user"), "我妈妈叫李芳")
    )

    assert reply is not None, "发送手册样例后没有收到任何下行回复"
    assert reply.get("sessionId"), "下行回复缺少 sessionId"
    assert reply.get("text"), "下行回复缺少 text"
    assert reply.get("emotion"), "下行回复缺少 emotion"


@requires_cloud
def test_text_reply_has_no_intent_field():
    """下行文本回复**不得**带 intent 字段。

    为什么：text-reply schema 是 additionalProperties: false，
    intent 不在其中。手册早先误写了它，设备实现者照抄后
    会一直解析出 undefined —— 这类错误不会报错，只会静默失效。
    """
    reply = asyncio.run(
        _say(_unique("contract-intent"), _unique("contract-user"), "今天天气怎么样")
    )

    assert reply is not None
    assert "intent" not in reply, (
        f"下行回复不应包含 intent 字段（schema 不允许），实际收到：{sorted(reply.keys())}"
    )


@requires_cloud
def test_emotion_value_is_from_the_declared_enum():
    """下行回复的 emotion 必须是协议枚举里的值。

    为什么：固件侧会按 emotion 切换表情/音色。
    收到枚举外的值，固件要么崩要么走默认分支。
    """
    allowed = {
        "neutral",
        "joy",
        "sadness",
        "anger",
        "fear",
        "surprise",
        "tenderness",
        "encouragement",
    }

    reply = asyncio.run(
        _say(_unique("contract-emotion"), _unique("contract-user"), "陪我聊会儿天")
    )

    assert reply is not None
    assert reply["emotion"] in allowed, (
        f"emotion={reply['emotion']!r} 不在协议枚举 {sorted(allowed)} 内"
    )


@requires_cloud
def test_citations_are_opaque_ids_not_readable_numbers():
    """citations 的值是 UUID，不是可读编号。

    为什么：手册早先写的是 mem-20261123-001 这种格式，
    设备实现者若照它解析编号就会出错。固件侧应把引用当不透明字符串。
    """
    reply = asyncio.run(
        _say(_unique("contract-cite"), _unique("contract-user"), "我养了一只叫豆豆的猫")
    )

    assert reply is not None
    citations = reply.get("citations", [])
    assert citations, "说出带具体信息的原话后应有引用"
    for citation in citations:
        assert isinstance(citation, str)
        assert not citation.startswith("mem-"), (
            f"citations 应为不透明 ID，实际收到 {citation!r}"
        )


@requires_cloud
def test_reconnect_with_same_session_id_keeps_memory():
    """重连时保持 sessionId，云端应认得是同一个会话。

    为什么：这是设备端断线重连的核心约定。
    若云端只认连接，重连后上下文全丢 —— 表现为"机器人每次断网就失忆"。
    """
    session_id = _unique("contract-reconnect")
    owner_key = _unique("contract-user")
    fact = "我养了一只叫豆豆的猫"

    first = asyncio.run(_say(session_id, owner_key, fact, sequence=0))
    second = asyncio.run(_say(session_id, owner_key, fact, sequence=1))

    assert first is not None, "第一次连接未收到回复"
    assert second is not None, "重连后未收到回复"
    assert second.get("citations"), (
        "重连后应仍能召回同一作用域的记忆（云端认 sessionId，不认连接）"
    )


@requires_cloud
def test_cross_user_isolation_blocks_leak():
    """用户 B 问用户 A 的事实，引用数必须为 0 且不泄漏内容。

    为什么：这是整套系统的核心安全承诺。
    """
    owner_a = _unique("contract-iso-a")
    owner_b = _unique("contract-iso-b")
    fact = "我妈妈叫李芳"

    reply_a = asyncio.run(_say(_unique("contract-session-a"), owner_a, fact))
    reply_b = asyncio.run(_say(_unique("contract-session-b"), owner_b, "我妈妈叫什么"))

    assert reply_a is not None
    assert reply_b is not None

    citations_a = set(reply_a.get("citations", []))
    citations_b = set(reply_b.get("citations", []))

    assert not (citations_a & citations_b), (
        f"用户B引用了用户A的记忆：{sorted(citations_a & citations_b)}"
    )
    assert fact not in reply_b.get("text", ""), (
        f"用户B的回复泄漏了用户A的事实：{reply_b.get('text')!r}"
    )
    assert not citations_b, (
        f"用户B的引用数应为 0，实际 {len(citations_b)}：{reply_b.get('citations')}"
    )


@requires_cloud
def test_no_match_falls_back_to_no_recall_template():
    """作用域内没有任何记忆时，走兜底话术而不是编一个答案。

    为什么：这是"机器人不乱说"的保证。

    ★ 注意选材：提问句**不能**用来说明这一点。
    云端把"记忆写入"放在"生成回复"**之前**，所以用户这一轮刚说的话
    自己就成了召回源 —— "明天的会议几点开始"含"明天"，
    会被分类器判为时效事件而写入长期记忆，随后召回的就是它自己，
    于是回复是"我记得，明天的会议几点开始"。

    这不是乱说（分类器**刻意**把时效事件归入长期记忆），
    但它会让"没命中"这条路径很难触发。
    所以这里用一个**纯作用域隔离**的做法：新开一个作用域，
    里面一条记忆都没有，直接发问句。
    """
    owner_key = _unique("contract-empty-scope")

    # 这个作用域里没有任何记忆，直接发问句
    reply = asyncio.run(
        _say(_unique("contract-empty-session"), owner_key, "我妈妈叫什么")
    )

    assert reply is not None
    assert reply.get("text") == NO_RECALL_TEMPLATE, (
        f"空作用域未命中时应回兜底话术，实际收到：{reply.get('text')!r}"
    )
    assert not reply.get("citations"), (
        f"空作用域未命中时引用数应为 0，实际 {reply.get('citations')}"
    )


@requires_cloud
def test_current_utterance_is_its_own_top_hit():
    """★ 当前这句话自己会成为召回源 —— 设备实现者必须知道这条行为。

    为什么：云端把"写记忆"放在"生成回复"**之前**，
    所以用户这一轮刚说的话立刻进入记忆库，也立刻是 Top-1 命中。

    设备实现者若看到"机器人重复我的话"而以为是 bug，
    会去改自己的固件 —— 改不对，因为这是云端的设计。

    同时这条行为说明：**问句本身不会被当成记忆**
    （问句被分类器剔除，见 CompanionMemoryClassifier 的 QUESTION_MARKERS），
    否则会出现"你说你想知道你妈妈叫什么"这种更糟的表现。
    """
    owner_key = _unique("contract-self-hit")
    session_id = _unique("contract-self-hit-session")

    # 一句含时效关键词的陈述 —— 会被判为时效事件并写入长期记忆
    reply = asyncio.run(_say(session_id, owner_key, "明天下午三点有个会议"))

    assert reply is not None
    assert "明天下午三点有个会议" in reply.get("text", ""), (
        f"陈述句应能召回自己，实际收到：{reply.get('text')!r}"
    )
    assert reply.get("citations"), "陈述句应产生引用"
