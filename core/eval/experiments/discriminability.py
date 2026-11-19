"""找出**真正能分开**"答得出"与"答不出"的判据。

问题
----
绝对相关性得分分不开这两类：
- 答得对的最低得分 0.4852（"我最近在忙什么" → "我正在准备考研"）；
- 答不出的最高得分 0.5268（"我住的地方有多大" → 误命中"我奶奶住在苏州"）。

两者重叠，任何单一阈值都只能在"少答几条"与"多编几条"之间二选一。

这个脚本横向比较几种判据，看哪一种能真正分开
--------------------------------------------
1. **绝对得分**     —— top1 得分；
2. **领先幅度**     —— top1 与 top2 的得分差；
3. **相对领先**     —— top1 与 top2 的得分比；
4. **峰值突出度**   —— top1 得分减去全部候选得分的均值
                      （问句很含糊时，全库得分会挤在一起，峰值就不突出）；
5. **分数集中度**   —— 全部候选得分的标准差（越集中说明越没有真正的峰值）。

判据 4 与 5 是新增的：它们问的不是"最像的那条有多像"，
而是"最像的那条**比其它所有条**突出多少"。
一个含糊的问句会让全库得分齐平，此时无论绝对值多高，都说明没找到。

跑法（在仓库根目录）：
    F:\\tools\\python313\\python.exe core\\eval\\experiments\\discriminability.py
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import numpy as np

CHROMA_BASE = "http://127.0.0.1:8765"
EMBEDDING_BASE = "http://127.0.0.1:8766"

TENANT = "default_tenant"
DATABASE = "default_database"
COLLECTION = "mem_longterm"
SCOPE_TENANT = "default"
SCOPE_OWNER = "discriminability-probe"

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

# 答得对的问句（问句与评测集不同，答案指向语料）。
ANSWERABLE = [
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

# 答不出的问句（语料里没有对应事实）。
UNANSWERABLE = [
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
            "ids": [f"disc-{index}" for index in range(len(corpus))],
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


def query_scores(collection_id: str, text: str, top_k: int = 13) -> list[tuple[str, float]]:
    """查询记忆库，返回 (文档, 得分) 列表。"""
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
    return [
        (document, 1.0 / (1.0 + distance))
        for document, distance in zip(body["documents"][0], body["distances"][0])
    ]


def features(scores: list[tuple[str, float]]) -> dict[str, float]:
    """从候选得分里算出各类判据的取值。"""
    values = [score for _, score in scores]
    top = values[0]
    second = values[1] if len(values) > 1 else 0.0
    mean = float(np.mean(values))
    std = float(np.std(values))
    return {
        "absolute": top,
        "margin": top - second,
        "relative": top / second if second > 0 else 0.0,
        "prominence": top - mean,
        "concentration": std,
    }


def main() -> None:
    """横向比较各类判据的分离能力。"""
    collection_id = resolve_collection_id()
    reset_scope(collection_id)
    write_corpus(collection_id, CORPUS)

    answerable_features: list[dict[str, float]] = []
    unanswerable_features: list[dict[str, float]] = []

    print("=== 答得对的问句 ===")
    for question, expected in ANSWERABLE:
        hits = query_scores(collection_id, question)
        top_document = hits[0][0]
        feature = features(hits)
        mark = "OK " if top_document == expected else "!! "
        if top_document == expected:
            answerable_features.append(feature)
        print(f"{mark}{question}")
        print(f"    第一={top_document}")
        print(f"    绝对={feature['absolute']:.4f} 领先={feature['margin']:+.4f} "
              f"相对={feature['relative']:.4f} 突出度={feature['prominence']:+.4f} "
              f"集中度={feature['concentration']:.4f}")

    print()
    print("=== 答不出的问句 ===")
    for question in UNANSWERABLE:
        hits = query_scores(collection_id, question)
        feature = features(hits)
        unanswerable_features.append(feature)
        print(f"    {question}")
        print(f"    第一={hits[0][0]}")
        print(f"    绝对={feature['absolute']:.4f} 领先={feature['margin']:+.4f} "
              f"相对={feature['relative']:.4f} 突出度={feature['prominence']:+.4f} "
              f"集中度={feature['concentration']:.4f}")

    print()
    print("=" * 78)
    print(f"答得对 {len(answerable_features)} 条（只统计排第一正确的），"
          f"答不出 {len(unanswerable_features)} 条")
    print()
    header = f"{'判据':<12} {'答得对最小值':>14} {'答不出最大值':>14} {'可分':>6}"
    print(header)
    print("-" * 78)
    for name in ["absolute", "margin", "relative", "prominence", "concentration"]:
        if not answerable_features:
            break
        low = min(f[name] for f in answerable_features)
        high = max(f[name] for f in unanswerable_features)
        separable = "是" if low > high else "否"
        print(f"{name:<12} {low:>14.4f} {high:>14.4f} {separable:>6}")
        if low > high:
            print(f"    => 合法阈值区间 ({high:.4f}, {low:.4f}]，可取中点 {(high + low) / 2:.4f}")

    reset_scope(collection_id)


if __name__ == "__main__":
    main()
