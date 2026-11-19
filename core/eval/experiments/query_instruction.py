"""测试检索侧能否做**原理性改进**，而不是靠调阈值掩盖问题。

背景
----
当前状况（均值池化，无查询指令）：
- 答得对的问句，最低得分 0.4852；
- 答不出的问句，最高得分 0.5268。

两者重叠 —— 也就是说"库里没有答案"与"答案在库里"在得分上分不开。
这是**检索能力**的局限，不是阈值选得不好。

候选改进：BGE 系列的查询指令前缀
--------------------------------
BGE-small-zh-v1.5 官方推荐在**查询侧**加一句检索指令
（"为句子生成表示以用于检索相关文章："），文档侧不加。
它的作用是让查询向量落在"检索"这个任务空间里，
从而与文档向量的分布对齐 —— 期望效果是：
- 答得对的问句得分**上移**；
- 答不出的问句得分**下移**（因为含糊的问句更靠近"泛化查询"而非具体事实）。

如果成立，重叠区间就会打开，从而得到一个**有余量**的阈值，
而不是现在这种"在 0.5268 与 0.5313 之间挤一条缝"的脆弱状态。

跑法（在仓库根目录）：
    F:\\tools\\python313\\python.exe core\\eval\\experiments\\query_instruction.py
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
SCOPE_OWNER = "instruction-probe"

# BGE 官方推荐的检索指令（中文版本）。
QUERY_INSTRUCTION = "为句子生成表示以用于检索相关文章："

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

# 评测集（门禁实际使用的 13 条）。
EVAL_SET = [
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

# 留出集：问句与评测集不同。
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
            "ids": [f"instr-{index}" for index in range(len(corpus))],
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


def query_scores(collection_id: str, text: str, with_instruction: bool,
                  top_k: int = 5) -> list[tuple[str, float]]:
    """查询记忆库，返回 (文档, 得分) 列表。"""
    query_text = QUERY_INSTRUCTION + text if with_instruction else text
    vector = embed([query_text])[0]
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


def run_scenario(collection_id: str, corpus: list[str], pairs: list[tuple[str, str]],
                 with_instruction: bool) -> dict[str, float]:
    """在给定配置下评估一组问句。"""
    reset_scope(collection_id)
    write_corpus(collection_id, corpus)
    correct_top = 0
    scores: list[float] = []
    for question, expected in pairs:
        hits = query_scores(collection_id, question, with_instruction)
        top_document, top_score = hits[0]
        scores.append(top_score)
        if top_document == expected:
            correct_top += 1
    return {
        "top1_correct": correct_top,
        "total": len(pairs),
        "min_score": min(scores),
        "mean_score": float(np.mean(scores)),
    }


def main() -> None:
    """对比有无查询指令的检索效果。"""
    collection_id = resolve_collection_id()

    for with_instruction in [False, True]:
        label = "带查询指令" if with_instruction else "无查询指令"
        print("=" * 72)
        print(f"### {label}")
        print("=" * 72)

        eval_result = run_scenario(collection_id, CORPUS, EVAL_SET, with_instruction)
        print(f"评测集 Top-1 正确: {eval_result['top1_correct']}/{eval_result['total']}  "
              f"最低得分={eval_result['min_score']:.4f}  平均得分={eval_result['mean_score']:.4f}")

        holdout = run_scenario(collection_id, CORPUS, HOLDOUT_ANSWERABLE, with_instruction)
        print(f"留出集 Top-1 正确: {holdout['top1_correct']}/{holdout['total']}  "
              f"最低得分={holdout['min_score']:.4f}  平均得分={holdout['mean_score']:.4f}")

        # 不可答问句：只看得分上界。
        reset_scope(collection_id)
        write_corpus(collection_id, CORPUS)
        unanswerable_scores: list[float] = []
        for question in HOLDOUT_UNANSWERABLE:
            hits = query_scores(collection_id, question, with_instruction)
            unanswerable_scores.append(hits[0][1])
        upper = max(unanswerable_scores)
        print(f"留出集不可答 最高得分={upper:.4f}  平均={float(np.mean(unanswerable_scores)):.4f}")

        lower = min(eval_result["min_score"], holdout["min_score"])
        print()
        if lower > upper:
            print(f"=> **可分！** 阈值区间 ({upper:.4f}, {lower:.4f}]，宽度 {lower - upper:.4f}")
            print(f"   可取中点 {(upper + lower) / 2:.4f}")
        else:
            print(f"=> 不可分：答得对最低 {lower:.4f} ≤ 答不出最高 {upper:.4f}，"
                  f"重叠宽度 {upper - lower:.4f}")
        print()

    reset_scope(collection_id)


if __name__ == "__main__":
    main()
