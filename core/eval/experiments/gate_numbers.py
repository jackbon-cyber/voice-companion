"""为最终实现确定三个数字：相关性下限、误答门禁、覆盖率门禁。

这一版把评测集补全
------------------
之前的记忆作答评测集**全是答得上的问题**。这是个致命缺口：
只测"答得上的问题"时，**永远拒答**的系统也能拿满分 ——
门禁形同虚设。所以评测集必须同时包含：

- **答得上的 13 条** —— 测"该答时答得对不对"；
- **答不上的 12 条** —— 测"不该答时会不会乱答"。

两组要分开记，因为它们性质完全不同：
- 对答得上的问题拒答 → **覆盖率损失**（机器人变迟钝）；
- 对答不上的问题作答 → **误答**（机器人乱说，会毁掉信任）。

阈值从**留出集**推导（留出集的问句与评测集不同），
评测集只用来**验收**。这样阈值不是"拿答案调出来的"。

跑法（在仓库根目录）：
    F:\\tools\\python313\\python.exe core\\eval\\experiments\\gate_numbers.py
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
SCOPE_OWNER = "gate-numbers-probe"

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

EVAL_ANSWERABLE = [
    ("我奶奶家在哪里", "我奶奶住在苏州"),
    ("我家养了几只小动物", "我养了三只仓鼠"),
    ("我最爱的菜是什么", "我最爱吃酸菜鱼"),
    ("我接下来有什么安排", "我下个月要参加同学的婚礼"),
    ("我有什么害怕的东西吗", "我怕黑"),
    ("我写字用什么手", "我习惯用左手写字"),
    ("我表姐在哪个城市工作", "我表姐在南京工作"),
    ("我的年龄是多少", "我今年三十五岁"),
    ("我一般什么时候去健身", "我每周三去健身房"),
    ("我有什么饮食禁忌吗", "我对芒果过敏"),
    ("我岳父有什么爱好", "我岳父喜欢下棋"),
    ("我的车是什么颜色", "我的车是白色的"),
    ("我最近在忙什么", "我正在准备考研"),
]

EVAL_UNANSWERABLE = [
    "我养的小狗叫什么名字",
    "我老家在哪个省份",
    "我姐姐的孩子多大了",
    "我的生日是几月几号",
    "我以前学过什么乐器",
    "我单位领导是谁",
    "我上次出差去了哪里",
    "我最喜欢的季节是哪个",
    "我明天几点起床",
    "我同事叫什么",
    "我上周看了什么电影",
    "我住的这栋楼有多少层",
]

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
    ("我最近忙的事情是什么", "我正在准备考研"),
    ("我下个月的日程是什么", "我下个月要参加同学的婚礼"),
]

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
    "我明天几点起床",
    "我同事叫什么",
    "我上周看了什么电影",
    "我住的这栋楼有多少层",
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
            "ids": [f"gate-{index}" for index in range(len(corpus))],
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


def query_top(collection_id: str, text: str, top_k: int = 5) -> tuple[str, float]:
    """查询记忆库，返回 (第一条文档, 得分)。"""
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
    document = body["documents"][0][0]
    distance = body["distances"][0][0]
    return document, 1.0 / (1.0 + distance)


def main() -> None:
    """给出最终三个数字。"""
    collection_id = resolve_collection_id()
    reset_scope(collection_id)
    write_corpus(collection_id, CORPUS)

    def tops(questions: list[str]) -> list[tuple[str, float]]:
        """测一批问句的第一条命中与得分。"""
        return [query_top(collection_id, question) for question in questions]

    eval_answerable = tops([q for q, _ in EVAL_ANSWERABLE])
    eval_unanswerable = tops(EVAL_UNANSWERABLE)
    holdout_answerable = tops([q for q, _ in HOLDOUT_ANSWERABLE])
    holdout_unanswerable = tops(HOLDOUT_UNANSWERABLE)

    print("=== 评测集：答得上的 13 条 ===")
    for (question, expected), (document, score) in zip(EVAL_ANSWERABLE, eval_answerable):
        mark = "OK " if document == expected else "!! "
        print(f"{mark}{question:<16} 第一={document:<14} 得分={score:.4f}")

    print()
    print("=== 评测集：答不上的 12 条 ===")
    for question, (document, score) in zip(EVAL_UNANSWERABLE, eval_unanswerable):
        print(f"    {question:<16} 第一={document:<14} 得分={score:.4f}")

    print()
    print("=== 留出集：答得上的 15 条 ===")
    for (question, expected), (document, score) in zip(HOLDOUT_ANSWERABLE, holdout_answerable):
        mark = "OK " if document == expected else "!! "
        print(f"{mark}{question:<18} 第一={document:<14} 得分={score:.4f}")

    print()
    print("=== 留出集：答不上的 14 条 ===")
    for question, (document, score) in zip(HOLDOUT_UNANSWERABLE, holdout_unanswerable):
        print(f"    {question:<18} 第一={document:<14} 得分={score:.4f}")

    # 留出集上的分离区间 —— 阈值的唯一来源。
    holdout_answerable_scores = [
        score for (question, expected), (_, score)
        in zip(HOLDOUT_ANSWERABLE, holdout_answerable)
        if query_top(collection_id, question)[0] == expected
    ]
    holdout_unanswerable_scores = [score for _, score in holdout_unanswerable]

    lower = min(holdout_answerable_scores)
    upper = max(holdout_unanswerable_scores)
    floor = (lower + upper) / 2

    print()
    print("=" * 78)
    print(f"留出集：答得对最低得分 = {lower:.4f}")
    print(f"留出集：答不出最高得分 = {upper:.4f}")
    print(f"分离区间 = ({upper:.4f}, {lower:.4f}]  宽度 {lower - upper:.4f}")
    print(f"=> 相关性下限取区间中点 = {floor:.4f}")
    print(f"   距两侧的余量各 {floor - upper:.4f} / {lower - floor:.4f}")

    print()
    print("=== 评测集验收（用留出集推出的阈值）===")
    floor = round(floor, 4)
    correct = 0
    fabricated = 0
    missed = 0
    refused_unanswerable = 0
    for (question, expected), (document, score) in zip(EVAL_ANSWERABLE, eval_answerable):
        if score < floor:
            missed += 1
        elif document == expected:
            correct += 1
        else:
            fabricated += 1
    for question, (document, score) in zip(EVAL_UNANSWERABLE, eval_unanswerable):
        if score < floor:
            refused_unanswerable += 1
        else:
            fabricated += 1

    total = len(EVAL_ANSWERABLE) + len(EVAL_UNANSWERABLE)
    accuracy = correct / (correct + fabricated) if (correct + fabricated) else 0.0
    coverage = correct / len(EVAL_ANSWERABLE)

    print(f"答对        = {correct}")
    print(f"误答（编造）= {fabricated}")
    print(f"漏答（该答却拒答）= {missed}")
    print(f"答不上的正确拒答 = {refused_unanswerable} / {len(EVAL_UNANSWERABLE)}")
    print()
    print(f"行为准确率 = {correct} / ({correct} + {fabricated}) = {accuracy:.4f}")
    print(f"覆盖率     = {correct} / {len(EVAL_ANSWERABLE)} = {coverage:.4f}")

    reset_scope(collection_id)


if __name__ == "__main__":
    main()
