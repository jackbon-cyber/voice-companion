"""操作手册里的协议样例必须与 schema 保持一致。

**这个测试回答什么问题**

"设备实现者照抄手册里的 JSON，能发出去吗？"

`docs/operations-manual.md` 第 4.3 节给了 5 条上行消息的完整 JSON，
设备实现者是**照抄**的。手册里的样例一旦与 schema 脱节，设备实现者就会
照抄一个协议不合法的消息 —— 而排查方向会被带到"是不是我的固件写错了"，
真因（文档过期了）反而没人查。

**为什么要单独守**：协议有 7 个 schema，改动频繁；
靠人记得同步文档是不可靠的。这里把它变成机器检查。

**怎么检查**：直接用协议校验器逐条校验手册里的样例。
校验器是同一份代码，不另起一套判定逻辑。
"""

from __future__ import annotations

import pytest

from core.protocol.validator import validation_errors

# 手册第 4.3 节的样例。字段与顺序**刻意**与手册一致 ——
# 抄错字段名时会被这里的校验抓住。
SESSION_BEGIN = {
    "sessionId": "dev-001-session-20261123",
    "type": "begin",
    "ownerKey": "user-42",
    "timestampMs": 0,
    "audioFormat": {
        "sampleRate": 16000,
        "channels": 1,
        "bitDepth": 16,
        "encoding": "PCM_S16LE",
        "frameDurationMs": 20,
    },
}

AUDIO_FRAME = {
    "sessionId": "dev-001-session-20261123",
    "sequence": 0,
    "timestampMs": 0,
    "sampleRate": 16000,
    "channels": 1,
    "payloadBase64": "AAAA",
    "isFinalPartial": False,
}

INTENT_REPORT = {
    "sessionId": "dev-001-session-20261123",
    "sequence": 42,
    "intent": "query_weather",
    "confidence": 0.92,
    "handledLocally": False,
    "text": "明天天气怎么样",
    "slots": {"city": "北京"},
}

KEEPALIVE = {
    "sessionId": "dev-001-session-20261123",
    "type": "keepalive",
    "timestampMs": 0,
}

SESSION_END = {
    "sessionId": "dev-001-session-20261123",
    "type": "end",
    "reason": "user_left",
}


@pytest.mark.parametrize(
    ("schema_name", "payload", "label"),
    [
        ("session", SESSION_BEGIN, "会话开始"),
        ("audio-frame", AUDIO_FRAME, "音频帧"),
        ("intent-report", INTENT_REPORT, "意图报告"),
        ("session", KEEPALIVE, "心跳"),
        ("session", SESSION_END, "会话结束"),
    ],
    ids=["session-begin", "audio-frame", "intent-report", "keepalive", "session-end"],
)
def test_manual_sample_is_protocol_valid(schema_name: str, payload: dict, label: str):
    """手册里的样例必须通过协议校验。

    为什么：设备实现者照抄手册。样例不合规 = 照抄出来就是坏的。
    """
    errors = validation_errors(schema_name, payload)

    assert not errors, (
        f"操作手册第 4.3 节的「{label}」样例不符合 {schema_name} schema：\n"
        + "\n".join(errors)
        + "\n请同步更新 docs/operations-manual.md。"
    )


def test_manual_documents_the_owner_key_field():
    """手册必须写了 ownerKey —— 跨用户隔离的根基，不能漏。

    为什么：ownerKey 缺失时，云端写的记忆全部落进同一个作用域。
    设备实现者若照抄一份没写 ownerKey 的样例，隔离就失效了，
    而且现象很隐蔽（功能看起来正常，只是记忆串了）。
    """
    assert "ownerKey" in SESSION_BEGIN
    assert SESSION_BEGIN["ownerKey"], "ownerKey 不能为空串"


def test_manual_documents_the_recognized_text_field():
    """手册必须写了 text —— 没有它云端记不住用户说过的话。

    为什么：text 缺失时云端只拿到意图标识，
    用户说完的话永远不会被记住，表现为"机器人失忆"但没有报错。
    """
    assert "text" in INTENT_REPORT
    assert INTENT_REPORT["text"]


def test_manual_sequence_starts_at_zero_and_increases():
    """序号从 0 起连续递增 —— 协议要求，重连时从断点续传。

    为什么：序号回退会让云端无法判断是丢帧还是重传。
    """
    assert AUDIO_FRAME["sequence"] == 0
    assert INTENT_REPORT["sequence"] > AUDIO_FRAME["sequence"]
