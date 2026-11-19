"""在**三份互不重合的数据**上交叉验证相关性下限。

三份数据的作用各不相同
----------------------
1. **留出集**（问句与评测集不同）—— 用来**定阈值**，避免在评测集上过拟合；
2. **评测集**（门禁实际使用的那 13 条）—— 用来**验阈值**，看门禁能否通过；
3. **端到端关键问句** —— 用来**查副作用**，看端到端断言依赖的召回会不会被拒答掉。

一份阈值必须**三份都成立**才算可用：
只在评测集上成立 = 过拟合；让端到端断言失效 = 副作用。

跑法（在仓库根目录）：
    F:\\tools\\python313\\python.exe core\\eval\\experiments\\cross_validate_floor.py
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
SCOPE_OWNER = "cross-validate-probe"

# 阈值候选：留出集给出的区间是 (0.5268, 0.5313]。
# 这里一并测几个邻近值，看阈值的**敏感度** ——
# 阈值离边界越近，换批数据就越容易失效。
FLOOR_CANDIDATES = [0.470, 0.476, 0.500, 0.520, 0.527, 0.529, 0.531, 0.540, 0.560]

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

# 留出集（用于定阈值）。
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

# 端到端关键问句（端到端断言依赖它们必须能召回）。
E2E_CRITICAL = [
    ("我妈妈叫李芳", "我妈妈叫什么"),
    ("我最喜欢吃红烧肉", "我最喜欢吃什么"),
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
            "ids": [f"cross-{index}" for index in range(len(corpus))],
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


def query_scores(collection_id: str, text: str, top_k: int = 5) -> list[tuple[str, float]]:
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


def evaluate(collection_id: str, corpus: list[str], pairs: list[tuple[str, str]],
             floor: float) -> tuple[int, int]:
    """在给定下限下评估一组问句，返回 (作答数, 答对数)。"""
    reset_scope(collection_id)
    write_corpus(collection_id, corpus)
    answered = 0
    correct = 0
    for question, expected in pairs:
        hits = query_scores(collection_id, question)
        top_document, top_score = hits[0]
        if top_score < floor:
            continue
        answered += 1
        if top_document == expected:
            correct += 1
    return answered, correct


def main() -> None:
    """在三份数据上交叉验证阈值。"""
    collection_id = resolve_collection_id()

    eval_corpus = [expected for _, expected in EVAL_SET]
    holdout_corpus = [expected for _, expected in HOLDOUT_ANSWERABLE]
    e2e_corpus = [original for original, _ in E2E_CRITICAL]

    print(f"{'下限':>6} | {'评测集 作答/答对':>16} {'准确率':>7} {'覆盖':>7} | "
          f"{'留出-可答 作答/答对':>20} | {'留出-不可答 误答':>16} | {'端到端 召回':>12}")
    print("-" * 108)

    for floor in FLOOR_CANDIDATES:
        eval_answered, eval_correct = evaluate(collection_id, eval_corpus, EVAL_SET, floor)

        holdout_answered, holdout_correct = evaluate(
            collection_id, holdout_corpus, HOLDOUT_ANSWERABLE, floor
        )

        # 不可答问句：统计"通过了下限却仍给出答案"的条数 —— 这些是误答。
        reset_scope(collection_id)
        write_corpus(collection_id, holdout_corpus)
        false_answers = 0
        for question in HOLDOUT_UNANSWERABLE:
            hits = query_scores(collection_id, question)
            if hits[0][1] >= floor:
                false_answers += 1

        e2e_answered, e2e_correct = evaluate(collection_id, e2e_corpus, E2E_CRITICAL, floor)

        eval_accuracy = eval_correct / eval_answered if eval_answered else 0.0
        eval_coverage = eval_answered / len(EVAL_SET)
        holdout_accuracy = holdout_correct / holdout_answered if holdout_answered else 0.0

        print(f"{floor:>6.3f} | {eval_answered:>7}/{eval_correct:<8} {eval_accuracy:>7.3f} "
              f"{eval_coverage:>7.3f} | {holdout_answered:>9}/{holdout_correct:<10} "
              f"{holdout_accuracy:>7.3f} | {false_answers:>16} | {e2e_correct:>6}/{len(E2E_CRITICAL)}")

    reset_scope(collection_id)


if __name__ == "__main__":
    main()
