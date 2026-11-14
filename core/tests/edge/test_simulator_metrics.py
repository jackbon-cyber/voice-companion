"""模拟端的分段耗时采集。

此前 {@code MetricsCollector} 的五个记录方法**没有任何调用方** ——
模拟端创建了采集器但一个样本都没录，导致指标报告永远是空的。
本文件把"采集器真的录到了东西"钉住。
"""

import pytest

from core.edge.audio.negotiation import DEFAULT_FORMAT
from core.edge.simulator import EdgeSimulator


@pytest.mark.asyncio
async def test_local_processing_metrics_are_recorded(serve_echo):
    """VAD、识别、意图三段耗时应各录到样本。"""

    async def handler(connection):
        async for _message in connection:
            pass

    async with serve_echo(handler) as base_url:
        simulator = EdgeSimulator(
            session_id="s-metrics",
            cloud_url=base_url,
            phrases=["把音量调到五十"],
        )
        await simulator.run(rounds=1)

    counts = simulator.metrics.snapshot().sample_counts
    assert counts["vad"] > 0, "VAD 耗时应被采集"
    assert counts["asr"] > 0, "识别耗时应被采集"
    assert counts["intent"] > 0, "意图判定耗时应被采集"


@pytest.mark.asyncio
async def test_round_trip_is_recorded_when_cloud_replies(serve_echo):
    """云端回复到达时，上云往返耗时应被记录。"""
    import json

    async def handler(connection):
        async for message in connection:
            payload = json.loads(message)
            if "intent" in payload:
                await connection.send(
                    json.dumps(
                        {
                            "sessionId": payload["sessionId"],
                            "text": "好的，我把音量调到五十。",
                            "emotion": "neutral",
                        }
                    )
                )

    async with serve_echo(handler) as base_url:
        simulator = EdgeSimulator(
            session_id="s-metrics",
            cloud_url=base_url,
            phrases=["今天发生了好多事情啊"],
        )
        await simulator.run(rounds=1)

    counts = simulator.metrics.snapshot().sample_counts
    assert counts["round_trip"] > 0, "上云往返耗时应被采集"


@pytest.mark.asyncio
async def test_first_packet_latency_is_recorded_on_text_reply(serve_echo):
    """云端只发文本回复时，首包延迟仍要有样本。

    若只在语音片段上统计首包，这项指标在第一阶段永远是空的 ——
    而"未采集到样本"会被报告标成未覆盖，白白丢掉一个真实可测的量。
    """
    import json

    async def handler(connection):
        async for message in connection:
            payload = json.loads(message)
            if "intent" in payload:
                await connection.send(
                    json.dumps(
                        {
                            "sessionId": payload["sessionId"],
                            "text": "我听着呢，你继续说。",
                            "emotion": "tenderness",
                        }
                    )
                )

    async with serve_echo(handler) as base_url:
        simulator = EdgeSimulator(
            session_id="s-metrics",
            cloud_url=base_url,
            phrases=["今天发生了好多事情啊"],
        )
        await simulator.run(rounds=1)

    counts = simulator.metrics.snapshot().sample_counts
    assert counts["first_packet"] > 0, "首包延时应被采集"


@pytest.mark.asyncio
async def test_offline_run_records_local_metrics_only(serve_echo):
    """离线时没有往返与首包样本 —— 报告要能把这两项标为"未采集到"。

    静默填 0 会让"没测到"看起来像"测出来是 0"。
    """

    async def handler(connection):
        async for _message in connection:
            pass

    async with serve_echo(handler) as base_url:
        simulator = EdgeSimulator(
            session_id="s-metrics",
            cloud_url="ws://127.0.0.1:1/voice/uplink",
            phrases=["今天好难过"],
        )
        await simulator.run(rounds=1)

    counts = simulator.metrics.snapshot().sample_counts
    assert counts["asr"] == 0, "离线时识别由脚本直接给出，不经识别器"
    assert counts["round_trip"] == 0, "离线时没有往返"


@pytest.mark.asyncio
async def test_metrics_are_exported_to_files(serve_echo, tmp_path):
    """模拟端能把指标报告导出成文件。"""

    async def handler(connection):
        async for _message in connection:
            pass

    markdown_path = tmp_path / "metrics.md"
    json_path = tmp_path / "metrics.json"

    async with serve_echo(handler) as base_url:
        simulator = EdgeSimulator(
            session_id="s-metrics",
            cloud_url=base_url,
            phrases=["把音量调到五十"],
        )
        await simulator.run(rounds=1)

    from core.edge.metrics.reporter import MetricsReporter

    reporter = MetricsReporter(simulator.metrics)
    reporter.export_markdown(markdown_path, {"env": "test"})
    reporter.export_json(json_path, {"env": "test"})

    assert markdown_path.exists()
    assert json_path.exists()
    assert "语音活动判定" in markdown_path.read_text(encoding="utf-8")
