"""用**留出集**推导相关性下限，而不是在评测集上挑阈值。

为什么必须用留出集
------------------
评测集（core/eval/memory_answer-eval.txt）就是门禁要用的那 13 条。
**在那 13 条上挑一个"能过线"的阈值，是过拟合**：
阈值会精确地贴合这 13 条的分布，换一批数据立刻失效。
拿它去当门禁，等于用答案调答案。

所以这里另建一份**留出集**：
- 语料**与评测集相同**（同一批记忆事实，这是生产形态）；
- 问句**全部重新写**（不与评测集重合）；
- 额外加一批**库里根本没有答案**的干扰问句。

留出集能回答两个问题：

1. **答得对的时候，得分分布长什么样**（下界在哪）；
2. **库里没有答案时，系统会拿到多高的得分**（上界在哪）。

这两个数之间的空隙，就是相关性下限的合法取值区间 ——
它由**留出集**决定，与评测集无关，因此不会过拟合。

跑法（在仓库根目录）：
    F:\\tools\\python313\\python.exe core\\eval\\experiments\\holdout_threshold.py
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

CHROMA_BASE = "http://127.0.0.1:8765"
EMBEDDING_BASE = "http://127.0.0.1:8766"

TENANT = "default_tenant"
DATABASE = "default_database"
COLLECTION = "mem_longterm"
SCOPE_TENANT = "default"
SCOPE_OWNER = "holdout-probe"

# 语料与评测集相同：同一批记忆事实。
CORPUS = [
    "我奶奶住在苏州",
    "我养了三只仓鼠",
    "我最爱吃酸菜鱼",
    "我下个月要参加同学的婚礼",
    "我怕黑",
    "我习惯用左手写字",
    "我表姐在南京工作",
    "我今年三十五岁",
    "我每周三去健身房",
    "我对芒果过敏",
    "我岳父喜欢下棋",
    "我的车是白色的",
    "我正在准备考研",
]

# 留出集：问句全部重新写，答案指向语料中的某一条。
# **语料与评测集相同，问句与评测集不同** —— 测的是同一批事实在新问法下的表现。
HOLDOUT_ANSWERABLE = [
    ("我奶奶平日住在哪个城市", "我奶奶住在苏州"),
    ("我家养的小动物有几只", "我养了三只仓鼠"),
    ("我最喜欢做的菜是哪一道", "我最爱吃酸菜鱼"),
    ("下个月我要去参加什么活动", "我下个月要参加同学的婚礼"),
    ("有什么东西是我特别害怕的", "我怕黑"),
    ("我平常写字惯用哪只手", "我习惯用左手写字"),
    ("我表姐上班的地方在哪里", "我表姐在南京工作"),
    ("我的年龄到底多大", "我今年三十五岁"),
    ("我固定在星期几去锻炼身体", "我每周三去健身房"),
    ("芒果这类东西我能不能吃", "我对芒果过敏"),
    ("我岳父平常爱做哪件事", "我岳父喜欢下棋"),
    ("我的车漆是什么颜色", "我的车是白色的"),
    ("我眼下在忙着准备哪件事", "我正在准备考研"),
]

# 留出集的干扰项：语料里**根本没有**对应事实。
#
# **这一组最关键**：它给出"库里没有答案时系统会拿到多高的得分"，
# 也就是相关性下限必须挡住的那一侧。
HOLDOUT_UNANSWERABLE = [
    "我养的小狗叫什么名字",
    "我老家在哪个省份",
    "我姐姐的孩子多大了",
    "我的生日是几月几号",
    "我住的地方有多大",
    "我以前学过什么乐器",
    "我单位领导是谁",
    "我上次出差去了哪里",
    "我最喜欢的季节是哪个",
    "我养过什么品种的猫",
]


def request_json(url: str, payload: dict | None = None, method: str = "POST") -> object:
    """发起一次 JSON 请求。"""
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method=method
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"HTTP {error.code}: {error.read().decode('utf-8')}") from error
    return json.loads(body) if body else None


def embed(texts: list[str]) -> list[list[float]]:
    """调用本地嵌入服务取向量。"""
    body = request_json(f"{EMBEDDING_BASE}/v1/embeddings", {"input": texts})
    return [item["embedding"] for item in body["data"]]


def collections_url() -> str:
    """返回集合列表地址。"""
    return f"{CHROMA_BASE}/api/v2/tenants/{TENANT}/databases/{DATABASE}/collections"


def resolve_collection_id() -> str:
    """查出集合 id。"""
    for item in request_json(collections_url(), method="GET"):
        if item.get("name") == COLLECTION:
            return item["id"]
    raise RuntimeError(f"集合不存在：{COLLECTION}")


def scope_where() -> dict:
    """返回作用域过滤条件。"""
    return {
        "$and": [
            {"scope_tenant": {"$eq": SCOPE_TENANT}},
            {"scope_owner": {"$eq": SCOPE_OWNER}},
        ]
    }


def reset_scope(collection_id: str) -> None:
    """清空本脚本的作用域。"""
    request_json(
        f"{collections_url()}/{collection_id}/delete", {"where": scope_where()}
    )


def write_corpus(collection_id: str, corpus: list[str]) -> None:
    """把语料写入记忆库。"""
    vectors = embed(corpus)
    request_json(
        f"{collections_url()}/{collection_id}/add",
        {
            "ids": [f"holdout-{index}" for index in range(len(corpus))],
            "embeddings": vectors,
            "documents": corpus,
            "metadatas": [
                {
                    "scope_tenant": SCOPE_TENANT,
                    "scope_owner": SCOPE_OWNER,
                    "weight": 1.0,
                    "created_at": 1_000_000 + index,
                    "archived": False,
                }
                for index in range(len(corpus))
            ],
        },
    )


def query(collection_id: str, text: str, top_k: int = 5) -> list[tuple[str, float]]:
    """查询记忆库，返回 (文档, 距离) 列表。"""
    vector = embed([text])[0]
    body = request_json(
        f"{collections_url()}/{collection_id}/query",
        {
            "query_embeddings": [vector],
            "n_results": top_k,
            "include": ["documents", "distances"],
            "where": scope_where(),
        },
    )
    return list(zip(body["documents"][0], body["distances"][0]))


def main() -> None:
    """在留出集上推导相关性下限。"""
    collection_id = resolve_collection_id()
    reset_scope(collection_id)
    write_corpus(collection_id, CORPUS)

    print("=== 留出集：答得对的问句 ===")
    answerable_scores: list[float] = []
    answerable_margins: list[float] = []
    wrong_hits = 0
    for question, expected in HOLDOUT_ANSWERABLE:
        hits = query(collection_id, question)
        documents = [document for document, _ in hits]
        scores = [1.0 / (1.0 + distance) for _, distance in hits]
        top_document = documents[0]
        margin = scores[0] - scores[1] if len(scores) > 1 else 0.0
        if top_document == expected:
            answerable_scores.append(scores[0])
            answerable_margins.append(margin)
            mark = "OK "
        else:
            wrong_hits += 1
            mark = "!! "
        print(f"{mark}{question}")
        print(f"    期望 {expected}  实际 {top_document}")
        print(f"    得分={scores[0]:.4f}  领先={margin:+.4f}")

    print()
    print("=== 留出集：库里没有答案的干扰问句 ===")
    unanswerable_scores: list[float] = []
    unanswerable_margins: list[float] = []
    for question in HOLDOUT_UNANSWERABLE:
        hits = query(collection_id, question)
        scores = [1.0 / (1.0 + distance) for _, distance in hits]
        margin = scores[0] - scores[1] if len(scores) > 1 else 0.0
        unanswerable_scores.append(scores[0])
        unanswerable_margins.append(margin)
        print(f"    {question}")
        print(f"        最高得分={scores[0]:.4f}  领先={margin:+.4f}")

    print()
    print("=" * 64)
    print(f"答得对时的最高得分下界 = {min(answerable_scores):.4f}")
    print(f"答得对时的领先幅度下界 = {min(answerable_margins):+.4f}")
    print(f"答错（排第一不是期望值）条数 = {wrong_hits}")
    print()
    print(f"库中无答案时的最高得分上界 = {max(unanswerable_scores):.4f}")
    print(f"库中无答案时的领先幅度上界 = {max(unanswerable_margins):+.4f}")
    print()
    print("=> 相关性下限的合法取值区间（要挡住无答案，也要留住有答案）：")
    lower = max(unanswerable_scores)
    upper = min(answerable_scores)
    print(f"    ({lower:.4f}, {upper:.4f}]")
    if lower < upper:
        print(f"    可取中点 {(lower + upper) / 2:.4f}")
    else:
        print("    **区间为空 —— 说明单靠绝对得分分不开，需要相对判据**")

    print()
    print("=> 领先幅度的合法取值区间：")
    lower_m = max(unanswerable_margins)
    upper_m = min(answerable_margins)
    print(f"    ({lower_m:+.4f}, {upper_m:+.4f}]")
    if lower_m < upper_m:
        print(f"    可取中点 {(lower_m + upper_m) / 2:+.4f}")
    else:
        print("    **区间为空 —— 说明单靠领先幅度也分不开**")

    reset_scope(collection_id)


if __name__ == "__main__":
    main()
