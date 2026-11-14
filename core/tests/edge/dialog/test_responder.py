from core.edge.dialog.engine import PhraseBankDialogEngine
from core.edge.dialog.responder import (
    LOCAL_SOURCE,
    LocalReply,
    LocalResponder,
)


def _responder() -> LocalResponder:
    return LocalResponder(engine=PhraseBankDialogEngine())


def test_reply_is_marked_as_locally_produced():
    """本地应答必须标记来源，不能伪装成云端结果。"""
    reply = _responder().respond("今天太开心了")
    assert reply.source == LOCAL_SOURCE
    assert reply.locally_produced is True


def test_reply_picks_emotion_bucket_by_detected_emotion():
    """情感标签决定取哪个桶的候选句。"""
    reply = _responder().respond("今天好难过")
    assert reply.emotion == "sadness"


def test_reply_text_is_not_empty():
    reply = _responder().respond("随便聊聊")
    assert reply.text != ""


def test_factual_request_gets_guidance_without_facts():
    """事实性请求只能给引导话术，不得含事实内容。"""
    reply = _responder().respond_factual("我上次的血压是多少")
    assert reply.factual_guard is True
    assert reply.text != ""
    # 引导话术不应出现具体数值
    assert "120" not in reply.text and "80" not in reply.text


def test_offline_factual_reply_mentions_being_offline():
    """离线时必须说明自己连不上网络，不能让用户等一个不会来的答案。"""
    reply = _responder().respond_factual("今天天气怎么样", offline=True)
    assert reply.offline is True
    assert "网络" in reply.text or "联网" in reply.text


def test_online_factual_reply_does_not_claim_to_be_offline():
    reply = _responder().respond_factual("今天天气怎么样", offline=False)
    assert reply.offline is False


def test_offline_companion_reply_is_marked_offline():
    reply = _responder().respond("我有点害怕", offline=True)
    assert reply.offline is True
    assert reply.locally_produced is True


def test_local_reply_default_source_is_local():
    reply = LocalReply(text="我在的")
    assert reply.source == LOCAL_SOURCE
