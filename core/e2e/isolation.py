"""端到端验证：跨用户记忆隔离与离线降级。

这个模块是**端到端断言的执行体**，不是单元测试替身 ——
它连真实的云端（WebSocket + Chroma + 嵌入服务），跑真实的端侧模拟端，
然后从**下行协议消息**里读取引用来源做判定。

为什么断言放在协议层而不是函数返回值上：
「用户 A 的记忆没有泄漏给用户 B」这件事，只有在**回复消息里**才能被观察。
如果只断言内部函数返回值，一旦某个环节把回复与记忆脱节
（比如回复走了另一条渲染路径），断言照样通过，而实际行为是泄漏的。

判定依据是 ``text-reply`` 协议里的 ``citations`` 字段 ——
它列出了这条回复依据了哪几条记忆，是可机器判定的客观事实。

三个场景：

1. **在线隔离**：两个用户交替对话，各自的回复只引用自己的记忆。
2. **同源自洽**：同一用户连续对话，第二轮能召回第一轮的记忆。
3. **离线降级**：云端不可达时，端侧降级并本地应答，进程正常退出。

运行：

    python -m core.e2e.isolation --url ws://127.0.0.1:8080/voice/uplink
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.edge.simulator import EdgeSimulator
from core.edge.transport.downlink import TextReply

# 判定结论：全部通过。
RESULT_PASSED = "PASSED"

# 判定结论：存在失败项。
RESULT_FAILED = "FAILED"

# 判定结论：环境不可用（例如云端未启动）。
RESULT_ENV_UNAVAILABLE = "ENV_UNAVAILABLE"


@dataclass
class Exchange:
    """一次端云交互的观测结果。

    @param owner 用户标识
    @param text 用户本轮说的话
    @param reply_text 云端回复正文
    @param citations 回复引用的记忆标识
    @param emotion 情感标签
    """

    owner: str
    text: str
    reply_text: str = ""
    citations: list[str] = field(default_factory=list)
    emotion: str = ""

    @property
    def grounded(self) -> bool:
        """回复是否依据了记忆。

        @return 有引用来源返回 True
        """
        return bool(self.citations)


@dataclass
class CheckResult:
    """一项检查的结果。

    @param name 检查项名称
    @param passed 是否通过
    @param detail 详情
    """

    name: str
    passed: bool
    detail: str = ""


class E2eEnvironmentError(RuntimeError):
    """端到端环境不可用。

    与断言失败分开：环境不可用不是"功能不行"，
    而是"没法验证" —— 两者混为一谈会让报告把环境问题说成质量问题。
    """


class _ReplyCollector:
    """收集下行回复。

    挂在模拟端的下行观察者上，把收到的 `TextReply` 攒起来。
    """

    def __init__(self) -> None:
        self.replies: list[TextReply] = []

    def record(self, message: object) -> None:
        """记录一条下行消息。

        @param message 下行消息
        """
        if isinstance(message, TextReply):
            self.replies.append(message)

    def last(self) -> TextReply | None:
        """最近一条回复。

        @return 最近一条回复；没有时为 None
        """
        return self.replies[-1] if self.replies else None


async def _run_exchange(
    url: str,
    owner: str,
    session_id: str,
    phrases: list[str],
    timeout_seconds: float = 120.0,
) -> list[Exchange]:
    """让一个用户按顺序说完若干句话，收集每句的下行回复。

    @param url 云端上行地址
    @param owner 用户标识
    @param session_id 会话标识
    @param phrases 用户依次说的话
    @param timeout_seconds 整体超时秒数
    @return 每句话对应的观测结果
    @throws E2eEnvironmentError 云端不可达时抛出
    """
    simulator = EdgeSimulator(
        session_id=session_id,
        cloud_url=url,
        phrases=list(phrases),
        owner_key=owner,
    )
    collector = _ReplyCollector()
    simulator.set_downlink_observer(collector.record)

    exchanges: list[Exchange] = []
    try:
        # 模拟端的 run 会为每一轮从脚本里取下一句话。
        await asyncio.wait_for(simulator.run(rounds=len(phrases)), timeout=timeout_seconds)
    except asyncio.TimeoutError as error:
        raise E2eEnvironmentError(f"与云端的交互超时：{error}") from error

    for index, phrase in enumerate(phrases):
        reply = collector.replies[index] if index < len(collector.replies) else None
        exchanges.append(
            Exchange(
                owner=owner,
                text=phrase,
                reply_text=reply.text if reply else "",
                citations=list(reply.citations) if reply else [],
                emotion=reply.emotion if reply else "",
            )
        )

    return exchanges


async def run_isolation_checks(url: str) -> list[CheckResult]:
    """执行跨用户记忆隔离检查。

    **检查设计的要点**：用户 B 必须去问**只有用户 A 才知道**的事。

    为什么不能只让两个用户各说各的、再各自提问：
    那种设计下，B 的召回列表里**即使混进了 A 的记忆**，只要 B 自己的那条
    排在前面，回复正文与引用来源看起来仍然正常 ——
    检查会通过，而泄漏其实已经发生。
    换句话说，那种检查只在"泄漏的那条恰好排第一"时才拦得住，
    拦不住的是真正的隔离缺陷。

    让 B 直接问 A 的专属事实，泄漏就会**必然**出现在 B 的回复里。

    @param url 云端上行地址
    @return 检查结果列表
    @throws E2eEnvironmentError 云端不可达时抛出
    """
    results: list[CheckResult] = []

    user_a_fact = "我妈妈叫李芳"
    user_a_query = "我妈妈叫什么"
    user_b_fact = "我最喜欢吃红烧肉"
    user_b_query = "我最喜欢吃什么"

    try:
        # 用户 A：陈述事实 → 追问自己的事实。
        exchanges_a = await _run_exchange(
            url, "e2e-user-a", "e2e-session-a", [user_a_fact, user_a_query]
        )
        # 用户 B：陈述**另一件**事实 → 追问自己的事实 → **转问用户 A 的事实**。
        exchanges_b = await _run_exchange(
            url, "e2e-user-b", "e2e-session-b", [user_b_fact, user_b_query, user_a_query]
        )
    except E2eEnvironmentError:
        raise
    except (OSError, ConnectionError) as error:
        raise E2eEnvironmentError(f"云端不可达：{error}") from error

    if len(exchanges_a) < 2 or len(exchanges_b) < 3:
        raise E2eEnvironmentError("下行回复数量不足，无法判定隔离")

    # 检查一：用户 A 的追问应当召回自己的记忆。
    reply_a = exchanges_a[-1]
    results.append(
        CheckResult(
            name="用户A的回复引用自己的记忆",
            passed=reply_a.grounded and user_a_fact in reply_a.reply_text,
            detail=f"回复={reply_a.reply_text!r} 引用={reply_a.citations}",
        )
    )

    # 检查二：用户 B 的追问应当召回自己的记忆。
    # 这一条同时证明"隔离不是靠'谁都召不回'蒙混过关"——
    # 若记忆层整体失灵，这一条会失败，把检查二与检查三的空过堵住。
    reply_b_own = exchanges_b[1]
    results.append(
        CheckResult(
            name="用户B的回复引用自己的记忆",
            passed=reply_b_own.grounded and user_b_fact in reply_b_own.reply_text,
            detail=f"回复={reply_b_own.reply_text!r} 引用={reply_b_own.citations}",
        )
    )

    # 检查三：**泄漏检测**。用户 B 问的是只有用户 A 说过的事，
    # 若隔离失效，A 的记忆会出现在 B 的回复里。
    reply_b_leak = exchanges_b[-1]
    leaked = set(reply_a.citations) & set(reply_b_leak.citations)
    results.append(
        CheckResult(
            name="用户B问及用户A的事实时不泄漏",
            passed=not leaked and user_a_fact not in reply_b_leak.reply_text,
            detail=(
                f"回复={reply_b_leak.reply_text!r} 引用={reply_b_leak.citations}"
                f" 泄漏={sorted(leaked)}"
            ),
        )
    )

    # 检查四：用户 A 的回复里不得出现用户 B 的事实（反向泄漏）。
    leaked_reverse = set(reply_b_own.citations) & set(reply_a.citations)
    results.append(
        CheckResult(
            name="用户A的回复不引用用户B的记忆",
            passed=not leaked_reverse and user_b_fact not in reply_a.reply_text,
            detail=(
                f"回复={reply_a.reply_text!r} 引用={reply_a.citations}"
                f" 泄漏={sorted(leaked_reverse)}"
            ),
        )
    )

    return results


async def run_offline_checks(url: str) -> list[CheckResult]:
    """执行离线降级检查。

    @param url 云端上行地址（指向一个不可达的端口）
    @return 检查结果列表
    """
    simulator = EdgeSimulator(
        session_id="e2e-offline-session",
        cloud_url=url,
        phrases=["今天有点累", "随便聊两句"],
        owner_key="e2e-user-offline",
    )

    exit_code = 0
    try:
        await asyncio.wait_for(simulator.run(rounds=2), timeout=90.0)
    except asyncio.TimeoutError:
        exit_code = 1

    replies = simulator.local_replies

    return [
        CheckResult(
            name="离线时端侧产生本地应答",
            passed=len(replies) > 0,
            detail=f"本地应答数={len(replies)}",
        ),
        CheckResult(
            name="离线时进程正常退出",
            passed=exit_code == 0,
            detail=f"退出码={exit_code}",
        ),
        CheckResult(
            name="本地应答标记为本地来源",
            passed=bool(replies)
            and all(reply.source == simulator.LOCAL_REPLY_SOURCE for reply in replies),
            detail="本地应答均带 LOCAL 标记" if replies else "无本地应答",
        ),
        CheckResult(
            name="离线时进入降级档位",
            passed=simulator.is_offline,
            detail=f"降级档位={simulator.degrade_level().value}",
        ),
    ]


def write_report(results: list[CheckResult], report_path: Path) -> None:
    """把检查结果写成 JSON 报告。

    @param results 检查结果列表
    @param report_path 报告路径
    """
    payload: dict[str, Any] = {
        "result": RESULT_PASSED if all(item.passed for item in results) else RESULT_FAILED,
        "checks": [
            {"name": item.name, "passed": item.passed, "detail": item.detail}
            for item in results
        ],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    """脚本入口。

    @param argv 命令行参数
    @return 退出码
    """
    parser = argparse.ArgumentParser(description="端到端验证：跨用户记忆隔离与离线降级")
    parser.add_argument(
        "--url", default="ws://127.0.0.1:8080/voice/uplink", help="云端上行地址"
    )
    parser.add_argument(
        "--offline-url",
        default="ws://127.0.0.1:1/voice/uplink",
        help="故意不可达的地址，用于验证离线降级",
    )
    parser.add_argument(
        "--report", default="data/e2e-report.json", help="JSON 报告输出路径"
    )
    parser.add_argument("--skip-offline", action="store_true", help="跳过离线降级检查")
    args = parser.parse_args(argv)

    all_results: list[CheckResult] = []

    try:
        all_results.extend(asyncio.run(run_isolation_checks(args.url)))
    except E2eEnvironmentError as error:
        print(f"环境不可用：{error}", file=sys.stderr)
        print("请先启动云端：powershell -File core/scripts/start.ps1", file=sys.stderr)
        return 2

    if not args.skip_offline:
        all_results.extend(asyncio.run(run_offline_checks(args.offline_url)))

    report_path = Path(args.report)
    write_report(all_results, report_path)

    failed = [item for item in all_results if not item.passed]
    for item in all_results:
        marker = "OK  " if item.passed else "FAIL"
        print(f"[{marker}] {item.name}：{item.detail}")

    print()
    print(f"报告：{report_path}")
    if failed:
        print(f"共 {len(failed)} 项失败。")
        return 1
    print(f"全部 {len(all_results)} 项通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
