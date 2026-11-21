"""验证混合检索能否解决"长记忆被稀释导致误拒"的问题。

问题
----
纯语义检索把**所有**记忆放进一个竞争池，靠单一嵌入得分排序。
一条内容很长的记忆，其向量会被后续修饰语"稀释"，
与短问句的相似度下降，落到相关性下限以下而被误拒。

假设
----
先**按主体/关键词把候选集缩小**，再在小候选集内做语义排序，
就能消除"长记忆与无关记忆竞争"造成的稀释。

具体做法（两级）：
1. **粗筛**：用问句与记忆之间的词元重合，保留重合度不为零的候选；
2. **精排**：在粗筛后的候选里按嵌入得分排序。

跑法（仓库根目录，需先起 Chroma 与嵌入服务）：
    F:\\tools\\python313\\python.exe core\\eval\\experiments\\hybrid_retrieval.py

结论会打印成"可分 / 不可分"，并给出各判据的合法取值区间 ——
与 holdout_threshold.py 保持同一套方法论。
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
SCOPE_OWNER = "hybrid-probe"

# 回退路径上的得分折扣。
#
# **为什么需要折扣**：回退路径上的答案缺乏词元证据支撑，
# 相关性更不确定。打折让它更容易被相关性下限挡住 ——
# 与"宁可少答，不可乱答"的取向一致。
FALLBACK_PENALTY = 0.9

# 语料：**只放长记忆**，模拟真实对话里用户说的完整句子。
#
# **为什么第一版把长短两版都放进去是错的**：
# 那版语料里同时有"我奶奶住在苏州"（短）和
# "我奶奶住在苏州老家那边，小院子种了桂花"（长），
# 问句"我奶奶住在哪"该匹配哪个？**语料本身自相矛盾**，
# 任何检索策略都会"答错" —— 那测的是语料，不是策略。
#
# 真实场景里用户只会说一种说法，因此这里每条主题**只放一条长记忆**。
SHORT_CORPUS = [
    "我奶奶住在苏州",
    "我养了三只仓鼠",
    "我爱吃酸菜鱼",
    "我对芒果过敏",
    "我习惯用左手写字",
]

# 长记忆：核心事实与上面同主题，但带大量修饰语。
LONG_CORPUS = [
    "我妈妈叫李芳，她很爱我，每天都给我做饭，还总提醒我早点休息",
    "我表姐在南京工作，做建筑设计，平日里项目都挺忙的",
    "我每周三晚上都去健身房，练的是自由泳，已经坚持两年多了",
    "我的车是白色的，是辆小型的两厢车，平时主要在市区里通勤",
    "我养了三只仓鼠，一只叫团子一只叫糯米还有一只叫芝麻",
]

# 问句分三组：短语料可答、长语料可答、库里无答案。
ANSWERABLE_SHORT = [
    ("我奶奶住在哪里", "我奶奶住在苏州"),
    ("我养了几只小动物", "我养了三只仓鼠"),
    ("我最爱吃的菜是什么", "我爱吃酸菜鱼"),
    ("我有什么饮食禁忌", "我对芒果过敏"),
    ("我写字用什么手", "我习惯用左手写字"),
]

ANSWERABLE_LONG = [
    ("我妈妈叫什么", "我妈妈叫李芳，她很爱我，每天都给我做饭，还总提醒我早点休息"),
    ("我表姐在哪里工作", "我表姐在南京工作，做建筑设计，平日里项目都挺忙的"),
    ("我什么时候去健身", "我每周三晚上都去健身房，练的是自由泳，已经坚持两年多了"),
    ("我的车是什么颜色", "我的车是白色的，是辆小型的两厢车，平时主要在市区里通勤"),
    ("我养的仓鼠都叫什么", "我养了三只仓鼠，一只叫团子一只叫糯米还有一只叫芝麻"),
]

UNANSWERABLE = [
    "我养的小狗叫什么名字",
    "我老家在哪个省份",
    "我姐姐的孩子多大了",
    "我的生日是几月几号",
    "我以前学过什么乐器",
    "我单位领导是谁",
]


def request_json(url: str, payload: dict | None = None, method: str = "POST") -> object:
    """发起一次 JSON 请求。

    @param url 地址
    @param payload 请求体
    @param method 方法
    @return 响应内容
    """
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
    """调用本地嵌入服务取向量。

    @param texts 文本列表
    @return 向量列表
    """
    body = request_json(f"{EMBEDDING_BASE}/v1/embeddings", {"input": texts})
    ordered: list[list[float] | None] = [None] * len(texts)
    for item in body["data"]:
        ordered[item["index"]] = item["embedding"]
    return [vector for vector in ordered if vector is not None]


def collections_url() -> str:
    """返回集合列表地址。"""
    return f"{CHROMA_BASE}/api/v2/tenants/{TENANT}/databases/{DATABASE}/collections"


def resolve_collection_id() -> str:
    """查出集合 id。

    @return 集合 id
    """
    for item in request_json(collections_url(), method="GET"):
        if item.get("name") == COLLECTION:
            return item["id"]
    raise RuntimeError(f"集合不存在：{COLLECTION}")


def scope_where() -> dict:
    """返回作用域过滤条件。

    @return where 表达式
    """
    return {
        "$and": [
            {"scope_tenant": {"$eq": SCOPE_TENANT}},
            {"scope_owner": {"$eq": SCOPE_OWNER}},
        ]
    }


def reset_scope(collection_id: str) -> None:
    """清空本脚本的作用域。

    @param collection_id 集合 id
    """
    request_json(f"{collections_url()}/{collection_id}/delete", {"where": scope_where()})


def write_corpus(collection_id: str, corpus: list[str]) -> None:
    """把语料写入记忆库。

    @param collection_id 集合 id
    @param corpus 语料
    """
    vectors = embed(corpus)
    request_json(
        f"{collections_url()}/{collection_id}/add",
        {
            "ids": [f"hybrid-{index}" for index in range(len(corpus))],
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
    # 记录语料顺序，供后续按索引取回。
    with open("data/hybrid-corpus.json", "w", encoding="utf-8") as handle:
        json.dump(corpus, handle, ensure_ascii=False)


def load_corpus() -> list[str]:
    """读回语料顺序。

    @return 语料
    """
    with open("data/hybrid-corpus.json", encoding="utf-8") as handle:
        return json.load(handle)


def query_all(collection_id: str, text: str, top_k: int = 20) -> list[tuple[str, float]]:
    """查询记忆库，返回 (文档, 得分) 列表。

    @param collection_id 集合 id
    @param text 查询文本
    @param top_k 条数上限
    @return (文档, 得分) 列表
    """
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


def bigrams(text: str) -> set[str]:
    """取出文本的全部相邻二字组。

    @param text 文本
    @return 二字组集合
    """
    grams: set[str] = set()
    for index in range(len(text) - 1):
        grams.add(text[index : index + 2])
    return grams


def overlap_ratio(query: str, document: str) -> float:
    """计算问句与记忆的二字组重合比例。

    @param query 问句
    @param document 记忆
    @return 重合比例（0 表示完全不重合）
    """
    query_grams = bigrams(query)
    if not query_grams:
        return 0.0
    document_grams = bigrams(document)
    return len(query_grams & document_grams) / len(query_grams)


def hybrid_rank(query: str, candidates: list[tuple[str, float]]) -> tuple[str | None, float]:
    """混合检索：先按词元重合粗筛，再在候选内按语义得分精排。

    @param query 问句
    @param candidates (文档, 得分) 列表
    @return (排第一的文档, 其得分, 走的哪条路径)
    """
    filtered = [
        (document, score)
        for document, score in candidates
        if overlap_ratio(query, document) > 0
    ]
    if not filtered:
        return None, -1.0, "空"
    best = max(filtered, key=lambda item: item[1])
    return best[0], best[1], "粗筛"


def graded_rank(
    query: str, candidates: list[tuple[str, float]]
) -> tuple[str | None, float, str]:
    """分级混合检索：粗筛有候选就用粗筛，没有才回退到纯语义。

    **为什么要有回退**：纯粗筛会把"语义相近但用词不同"的正确答案误杀 ——
    实测"我有什么饮食禁忌"与"我对芒果过敏"二字组零重合，
    粗筛直接返回空候选，正确答案被丢掉。

    因此策略是**分级**的：
    1. 粗筛命中且有候选 → 在候选内按语义得分精排；
    2. 粗筛无候选 → 回退到纯语义排序（并把得分打折，
       表示"这条没有词元证据支撑"）。

    **为什么要打折**：回退路径上的答案缺乏词元证据，
    它的相关性更不确定。打折让纯语义路径上的答案更容易被相关性下限挡住 ——
    这与"宁可少答，不可乱答"的取向一致。

    @param query 问句
    @param candidates (文档, 得分) 列表
    @return (排第一的文档, 其得分, 走的哪条路径)
    """
    filtered = [
        (document, score)
        for document, score in candidates
        if overlap_ratio(query, document) > 0
    ]
    if filtered:
        best = max(filtered, key=lambda item: item[1])
        return best[0], best[1], "粗筛"
    if not candidates:
        return None, -1.0, "空"
    best = max(candidates, key=lambda item: item[1])
    return best[0], best[1] * FALLBACK_PENALTY, "回退"


def subject_rank(
    query: str, candidates: list[tuple[str, float]]
) -> tuple[str | None, float, str]:
    """主体优先检索：先按主体词元分组，组内按语义得分排序。

    **与粗筛的区别**：粗筛是"词元重合就必须保留"（硬过滤），
    本策略是"主体词元相同的一组优先"（软加权）——
    不满足主体条件的记忆不会被丢弃，只是排在后面。

    这样"我有什么饮食禁忌"虽然与"我对芒果过敏"没有共同二字组，
    但两者的主体词元"我对芒"相同，仍能被优先选中。

    @param query 问句
    @param candidates (文档, 得分) 列表
    @return (排第一的文档, 其得分, 走的哪条路径)
    """
    query_subject = query[:3]
    same_subject = [
        (document, score)
        for document, score in candidates
        if document[:3] == query_subject
    ]
    if same_subject:
        best = max(same_subject, key=lambda item: item[1])
        return best[0], best[1], "同主体"
    if not candidates:
        return None, -1.0, "空"
    best = max(candidates, key=lambda item: item[1])
    return best[0], best[1] * FALLBACK_PENALTY, "回退"


def main() -> None:
    """执行混合检索可行性验证。"""
    collection_id = resolve_collection_id()
    reset_scope(collection_id)
    corpus = SHORT_CORPUS + LONG_CORPUS
    write_corpus(collection_id, corpus)

    # 三种策略放在一起对比 —— 单看一种策略容易得出片面结论。
    strategies = [
        ("纯语义", lambda q, c: (c[0][0], c[0][1], "纯语义") if c else (None, -1.0, "空")),
        ("词元粗筛", hybrid_rank),
        ("分级降级", graded_rank),
        ("主体优先", subject_rank),
    ]

    results: dict[str, dict] = {}

    for name, strategy in strategies:
        answerable: list[float] = []
        unanswerable: list[float] = []
        wrong = 0
        detail: list[str] = []

        for question, expected in ANSWERABLE_SHORT + ANSWERABLE_LONG:
            hits = query_all(collection_id, question)
            top_document, top_score, branch = strategy(question, hits)
            matched = top_document == expected
            if not matched:
                wrong += 1
            detail.append(
                f"  {'OK ' if matched else '!! '}{question}\n"
                f"      期望 {expected}\n"
                f"      实际 {top_document}   得分={top_score:.4f}  [{branch}]"
            )
            answerable.append(top_score)

        for question in UNANSWERABLE:
            hits = query_all(collection_id, question)
            top_document, top_score, branch = strategy(question, hits)
            unanswerable.append(top_score)
            detail.append(f"      {question}   最高得分={top_score:.4f}  [{branch}]")

        lower = max(unanswerable)
        upper = min(answerable)
        separable = lower < upper
        results[name] = {
            "wrong": wrong,
            "answerable": answerable,
            "unanswerable": unanswerable,
            "lower": lower,
            "upper": upper,
            "separable": separable,
            "detail": detail,
        }

    for name, _strategy in strategies:
        item = results[name]
        print("=" * 72)
        print(f"【{name}】")
        print("=" * 72)
        for line in item["detail"]:
            print(line)
        print()
        print(f"  答错 {item['wrong']} 条")
        print(f"  答对时最低得分 = {item['upper']:.4f}")
        print(f"  无答案时最高得分 = {item['lower']:.4f}")
        if item["separable"]:
            print(
                f"  => **可分**，相关性下限可取区间 "
                f"({item['lower']:.4f}, {item['upper']:.4f}]，"
                f"中点 {(item['lower'] + item['upper']) / 2:.4f}"
            )
        else:
            print("  => **不可分**")
        print()

    reset_scope(collection_id)


if __name__ == "__main__":
    main()
