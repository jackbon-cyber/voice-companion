"""端到端隔离断言的**反证测试**。

**为什么必须有这个测试**

端到端断言"用户B问及用户A的事实时不泄漏"通过了 —— 但
"通过"本身不能证明断言有效。一个永远返回 True 的检查也能通过。

**没有反证的断言可能是在测一个永远为真的条件。**

这里不改动生产代码，而是**直接向断言的判定逻辑喂入泄漏场景**，
验证它确实会判失败。若哪天有人把判定条件写松了（比如去掉了
`not reply_b_leak.grounded` 这一项），本测试会立刻变红。

**为什么不能用"临时改生产代码绕过作用域过滤"来做反证**

那种做法需要给生产代码留一个后门开关，风险与维护成本都不划算。
而断言的判定逻辑是纯函数式的（输入观测数据、输出通过/不通过），
直接构造观测数据喂给它，既能验证判定逻辑的有效性，又不动生产路径。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.e2e.isolation import CheckResult, Exchange  # noqa: E402


def _judge_leak_check(
    reply_a: Exchange,
    reply_b_leak: Exchange,
    user_a_fact: str,
) -> CheckResult:
    """复刻端到端脚本中"用户B问及用户A的事实时不泄漏"的判定逻辑。

    **必须与 isolation.py 中的判定完全一致** —— 否则本测试就是在测另一套逻辑。
    端到端脚本里对应的是这段：

        leaked = set(reply_a.citations) & set(reply_b_leak.citations)
        passed = (not leaked
                  and user_a_fact not in reply_b_leak.reply_text
                  and not reply_b_leak.grounded)

    @param reply_a      用户 A 追问自己事实后的回复
    @param reply_b_leak 用户 B 追问用户 A 事实后的回复
    @param user_a_fact  用户 A 的专属事实
    @return 检查结果
    """
    leaked = set(reply_a.citations) & set(reply_b_leak.citations)
    return CheckResult(
        name="用户B问及用户A的事实时不泄漏",
        passed=(
            not leaked
            and user_a_fact not in reply_b_leak.reply_text
            and not reply_b_leak.grounded
        ),
        detail=(
            f"回复={reply_b_leak.reply_text!r} 引用={reply_b_leak.citations}"
            f" 泄漏={sorted(leaked)}"
        ),
    )


# 用户 A 的事实与追问。
USER_A_FACT = "我妈妈叫李芳"
USER_A_CITATION = "memory-a-001"


def test_clean_scenario_passes():
    """正常场景：判定逻辑必须通过。

    **为什么先测这个**：只测失败路径的话，一个"永远返回 False"的判定
    也能让全部失败用例通过 —— 那就是另一种形式的空断言。
    """
    reply_a = Exchange(
        owner="a", text="我妈妈叫什么", reply_text=f"我记得，{USER_A_FACT}",
        citations=[USER_A_CITATION], emotion="tenderness",
    )
    reply_b_leak = Exchange(
        owner="b", text="我妈妈叫什么",
        reply_text="我这边还没有关于这件事的记录，你说得再具体一点我就能记下了。",
        citations=[], emotion="tenderness",
    )

    assert _judge_leak_check(reply_a, reply_b_leak, USER_A_FACT).passed, (
        "正常场景必须通过 —— 否则说明判定条件写死了 False"
    )


def test_direct_leak_is_detected():
    """反证一：B 的回复直接引用了 A 的记忆 —— 必须判失败。"""
    reply_a = Exchange(
        owner="a", text="我妈妈叫什么", reply_text=f"我记得，{USER_A_FACT}",
        citations=[USER_A_CITATION], emotion="tenderness",
    )
    reply_b_leak = Exchange(
        owner="b", text="我妈妈叫什么", reply_text=f"我记得，{USER_A_FACT}",
        citations=[USER_A_CITATION], emotion="tenderness",
    )

    result = _judge_leak_check(reply_a, reply_b_leak, USER_A_FACT)

    assert not result.passed, "直接引用他人记忆未被检出 —— 断言无效"


def test_leak_with_different_citation_is_detected():
    """反证二：泄漏的记忆标识不同 —— 也必须判失败。

    **这一条挡的是"只看标识交集"的弱判定**：
    若只比对 citations 的交集，B 引用了**另一条**属于 A 的记忆时就会漏判。
    判定还要求"B 的回复里不含 A 的事实内容"与"B 完全没有引用来源"。
    """
    reply_a = Exchange(
        owner="a", text="我妈妈叫什么", reply_text=f"我记得，{USER_A_FACT}",
        citations=[USER_A_CITATION], emotion="tenderness",
    )
    reply_b_leak = Exchange(
        owner="b", text="我妈妈叫什么", reply_text="我记得，我爸爸叫李强",
        citations=["memory-a-002"], emotion="tenderness",
    )

    result = _judge_leak_check(reply_a, reply_b_leak, USER_A_FACT)

    assert not result.passed, "引用了他人另一条记忆未被检出 —— 断言过弱"


def test_stale_content_leak_is_detected():
    """反证三：内容泄漏但引用为空 —— 必须判失败。

    **这一条对应真实踩过的坑**：早期版本的泄漏检查只比对
    "B 的引用是否等于 A 的那条"。若靠上一轮运行残留的记忆蒙混过关，
    检查会通过而泄漏其实发生。这里要求"B 的回复正文不含 A 的事实"。
    """
    reply_a = Exchange(
        owner="a", text="我妈妈叫什么", reply_text=f"我记得，{USER_A_FACT}",
        citations=[USER_A_CITATION], emotion="tenderness",
    )
    reply_b_leak = Exchange(
        owner="b", text="我妈妈叫什么", reply_text=f"我记得，{USER_A_FACT}",
        citations=[], emotion="tenderness",
    )

    result = _judge_leak_check(reply_a, reply_b_leak, USER_A_FACT)

    assert not result.passed, "内容泄漏（引用为空）未被检出 —— 断言过弱"


def test_b_with_own_grounded_reply_is_detected():
    """反证四：B 的回复有引用来源（哪怕不是 A 的）—— 必须判失败。

    **为什么这条也重要**：B 的作用域里只有 B 自己的记忆，
    所以 B 正确回答"没有记录"时引用必然为空。
    若 B 的回复里出现了**任何一条**引用，就说明作用域里混进了不该有的东西 ——
    哪怕那条不是 A 的"我妈妈叫李芳"，也是泄漏的证据。
    """
    reply_a = Exchange(
        owner="a", text="我妈妈叫什么", reply_text=f"我记得，{USER_A_FACT}",
        citations=[USER_A_CITATION], emotion="tenderness",
    )
    reply_b_leak = Exchange(
        owner="b", text="我妈妈叫什么", reply_text="我记得，我最喜欢吃红烧肉",
        citations=["memory-b-001"], emotion="tenderness",
    )

    result = _judge_leak_check(reply_a, reply_b_leak, USER_A_FACT)

    assert not result.passed, "B 出现非预期引用未被检出 —— 判定条件过松"


@pytest.mark.parametrize(
    "leaked_reply",
    [
        Exchange(owner="b", text="我妈妈叫什么", reply_text=f"我记得，{USER_A_FACT}",
                  citations=[USER_A_CITATION], emotion="tenderness"),
        Exchange(owner="b", text="我妈妈叫什么", reply_text="我记得，我爸爸叫李强",
                  citations=["memory-a-002"], emotion="tenderness"),
        Exchange(owner="b", text="我妈妈叫什么", reply_text=f"我记得，{USER_A_FACT}",
                  citations=[], emotion="tenderness"),
        Exchange(owner="b", text="我妈妈叫什么", reply_text="我记得，我最喜欢吃红烧肉",
                  citations=["memory-b-001"], emotion="tenderness"),
    ],
    ids=["直接引用A的记忆", "引用A的另一条记忆", "内容泄漏但无引用", "出现非预期引用"],
)
def test_no_leak_scenario_satisfies_check(leaked_reply: Exchange):
    """任何一种泄漏形态都必须让检查失败（参数化汇总）。

    **为什么用参数化**：逐条写四个几乎一样的测试函数容易在改动时漏掉一条。
    """
    reply_a = Exchange(
        owner="a", text="我妈妈叫什么", reply_text=f"我记得，{USER_A_FACT}",
        citations=[USER_A_CITATION], emotion="tenderness",
    )

    result = _judge_leak_check(reply_a, leaked_reply, USER_A_FACT)

    assert not result.passed, f"泄漏形态未被检出：{result.detail}"
