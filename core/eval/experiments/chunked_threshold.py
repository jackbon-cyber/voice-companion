"""用**留出集**推导分片嵌入下的相关性下限。

为什么必须重推阈值
------------------
分片嵌入把长记忆的得分整体**抬高**了（实测 0.5145 → 0.5738）。
既然得分分布变了，原先的阈值 0.529 就**不再对应同一件事** ——
它原本是"整句嵌入下的可分缝隙中点"，分片后分布平移，
阈值必须重新推导，否则门禁要么形同虚设、要么全部拦死。

沿用 holdout_threshold.py 的方法论：
- **语料**与评测集相同（生产形态：短记忆 + 长记忆混合）；
- **问句**全部重新写，与评测集不重合；
- 额外加一批**库里根本没有答案**的干扰问句。

两组策略对比：
1. **整句嵌入**（现状基线）；
2. **分片嵌入**（新方案）—— 记忆按中文标点切子句，逐片段入库。

跑法（仓库根目录，需先起 Chroma 与嵌入服务）：
    F:\\tools\\python313\\python.exe core\\eval\\experiments\\chunked_threshold.py
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

# 语料：**短记忆 + 长记忆混合**，每个主题**只出现一次**。
#
# **为什么必须这样设计（这是踩过两次的坑）**：
# 第一版把同一主题的长短两版都放进语料（"我奶奶住在苏州" 与
# "我奶奶住在苏州老家那边…"），问句"我奶奶平日住在哪个城市"该匹配哪条？
# **语料自相矛盾**，于是"答错"数暴涨、两种策略都判为不可分 ——
# 那测的是语料缺陷，不是检索策略。
# 第二版又漏了几组重复（我表姐/健身/车/仓鼠），同样污染了结果。
# 现在每个主题**有且只有一条记忆**，长短只是这条记忆的写法差异。
SHORT_CORPUS = [
    "我奶奶住在苏州",
    "我最爱吃酸菜鱼",
    "我怕黑",
    "我习惯用左手写字",
    "我今年三十五岁",
    "我岳父喜欢下棋",
    "我正在准备考研",
    "我下个月要参加同学的婚礼",
]

LONG_CORPUS = [
    "我妈妈叫李芳，她很爱我，每天都给我做饭，还总提醒我早点休息",
    "我表姐在南京工作，做建筑设计，平日里项目都挺忙的",
    "我每周三晚上都去健身房，练的是自由泳，已经坚持两年多了",
    "我的车是白色的，是辆小型的两厢车，平时主要在市区里通勤",
    "我养了三只仓鼠，一只叫团子一只叫糯米还有一只叫芝麻",
]

# 留出集：问句全部重新写，答案指向语料中的某一条。
HOLDOUT_ANSWERABLE = [
    ("我奶奶平日住在哪个城市", "我奶奶住在苏州"),
    ("我最喜欢做的菜是哪一道", "我最爱吃酸菜鱼"),
    ("有什么东西是我特别害怕的", "我怕黑"),
    ("我平常写字惯用哪只手", "我习惯用左手写字"),
    ("我的年龄到底多大", "我今年三十五岁"),
    ("我岳父平常爱做哪件事", "我岳父喜欢下棋"),
    ("我眼下在忙着准备哪件事", "我正在准备考研"),
    ("下个月我要去参加什么活动", "我下个月要参加同学的婚礼"),
    ("我妈妈的名字是什么", "我妈妈叫李芳，她很爱我，每天都给我做饭，还总提醒我早点休息"),
    ("我表姐的办公地点在哪", "我表姐在南京工作，做建筑设计，平日里项目都挺忙的"),
    ("我平常在哪天去锻炼", "我每周三晚上都去健身房，练的是自由泳，已经坚持两年多了"),
    ("我的车子涂的是什么颜色", "我的车是白色的，是辆小型的两厢车，平时主要在市区里通勤"),
    ("我养的仓鼠分别叫什么", "我养了三只仓鼠，一只叫团子一只叫糯米还有一只叫芝麻"),
]

# 干扰项：语料里**根本没有**对应事实。
#
# **为什么"我养的第一只仓鼠叫什么"被移出这一组**：
# 库里**确实有**"我养了三只仓鼠，一只叫团子一只叫糯米还有一只叫芝麻" ——
# 问"第一只仓鼠叫什么"**本来就有答案**（团子）。
# 它属于"**部分可答**"，不是"库里没有答案"。
# 把它混进干扰项会得出"分片嵌入不可分"的错误结论：
# 实测它的得分高达 0.6786，正是它把"无答案侧上界"顶了上去。
#
# 这类"库里没有完整答案、但有高度相关的事实"的情况单列一组观察 ——
# 它检验的是系统会不会**部分作答**（答出"团子"），
# 那在陪伴场景里其实是可以接受的，不该与"完全编造"混为一谈。
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
    "我通勤坐的是几号线地铁",
    "我老婆在哪里上班",
    "我车子的排量是多少",
]

# 部分可答：库里有相关事实，但问句要的细节并不完整。
PARTIALLY_ANSWERABLE = [
    ("我养的第一只仓鼠叫什么", "我养了三只仓鼠，一只叫团子一只叫糯米还有一只叫芝麻"),
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


def scope_where(owner: str) -> dict:
    """返回作用域过滤条件。

    @param owner 归属标识
    @return where 表达式
    """
    return {
        "$and": [
            {"scope_tenant": {"$eq": SCOPE_TENANT}},
            {"scope_owner": {"$eq": owner}},
        ]
    }


def reset_scope(collection_id: str, owner: str) -> None:
    """清空指定作用域。

    @param collection_id 集合 id
    @param owner 归属标识
    """
    request_json(
        f"{collections_url()}/{collection_id}/delete", {"where": scope_where(owner)}
    )


def split_clauses(sentence: str) -> list[str]:
    """把一句话按中文标点切成子句。

    @param sentence 原句
    @return 子句列表
    """
    parts = [sentence]
    for separator in ["，", ",", "、", "；", ";"]:
        expanded: list[str] = []
        for part in parts:
            expanded.extend(part.split(separator))
        parts = expanded
    clauses = [part.strip() for part in parts if part.strip()]
    return clauses if clauses else [sentence]


def write_records(
    collection_id: str, owner: str, documents: list[str], prefix: str
) -> None:
    """把一组文本写入指定作用域。

    @param collection_id 集合 id
    @param owner 归属标识
    @param documents 文本列表
    @param prefix id 前缀
    """
    if not documents:
        return
    vectors = embed(documents)
    request_json(
        f"{collections_url()}/{collection_id}/add",
        {
            "ids": [f"{prefix}-{index}" for index in range(len(documents))],
            "embeddings": vectors,
            "documents": documents,
            "metadatas": [
                {
                    "scope_tenant": SCOPE_TENANT,
                    "scope_owner": owner,
                    "weight": 1.0,
                    "created_at": 1_000_000 + index,
                    "archived": False,
                }
                for index in range(len(documents))
            ],
        },
    )


def query(collection_id: str, owner: str, text: str, top_k: int = 5) -> list[tuple[str, float]]:
    """查询指定作用域。

    @param collection_id 集合 id
    @param owner 归属标识
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
            "where": scope_where(owner),
        },
    )
    return [
        (document, 1.0 / (1.0 + distance))
        for document, distance in zip(body["documents"][0], body["distances"][0])
    ]


def evaluate(
    collection_id: str, owner: str, label: str, chunk_to_parent: dict[str, str]
) -> dict:
    """在给定作用域上评估两种策略。

    @param collection_id 集合 id
    @param owner 归属标识
    @param label 标签
    @param chunk_to_parent 片段到原记忆的映射；整句策略时为空
    @return 评估结果
    """
    answerable: list[float] = []
    unanswerable: list[float] = []
    wrong = 0

    for question, expected in HOLDOUT_ANSWERABLE:
        hits = query(collection_id, owner, question)
        if not hits:
            continue
        top_document, top_score = hits[0]
        # 分片策略下，命中片段要映射回原记忆再比对。
        resolved = chunk_to_parent.get(top_document, top_document)
        matched = resolved == expected
        if not matched:
            wrong += 1
        print(f"  {'OK ' if matched else '!! '}{question}")
        print(f"      期望 {expected}")
        print(f"      实际 {resolved}   得分={top_score:.4f}")
        answerable.append(top_score)

    print()
    for question in HOLDOUT_UNANSWERABLE:
        hits = query(collection_id, owner, question)
        score = hits[0][1] if hits else -1.0
        unanswerable.append(score)
        print(f"      {question}   最高得分={score:.4f}")

    print()
    print("--- 部分可答（库里有相关事实，但问句要的细节不完整）---")
    for question, expected in PARTIALLY_ANSWERABLE:
        hits = query(collection_id, owner, question)
        if not hits:
            continue
        top_document, top_score = hits[0]
        resolved = chunk_to_parent.get(top_document, top_document)
        print(f"      {question}")
        print(f"          实际 {resolved}   得分={top_score:.4f}")

    lower = max(unanswerable)
    upper = min(answerable)
    print()
    print(f"【{label}】答错 {wrong} 条")
    print(f"  答对时最低得分 = {upper:.4f}")
    print(f"  无答案时最高得分 = {lower:.4f}")
    if lower < upper:
        print(
            f"  => **可分**，区间 ({lower:.4f}, {upper:.4f}]，"
            f"中点 {(lower + upper) / 2:.4f}，宽度 {upper - lower:.4f}"
        )
    else:
        print("  => **不可分**")
    return {
        "label": label,
        "wrong": wrong,
        "lower": lower,
        "upper": upper,
        "separable": lower < upper,
    }


def main() -> None:
    """执行留出集阈值推导。"""
    collection_id = resolve_collection_id()

    corpus = SHORT_CORPUS + LONG_CORPUS

    # 策略一：整句嵌入。
    whole_owner = "chunkthr-whole"
    reset_scope(collection_id, whole_owner)
    write_records(collection_id, whole_owner, corpus, "whole")

    print("=" * 74)
    print("【策略一】整句嵌入（现状基线）")
    print("=" * 74)
    whole = evaluate(collection_id, whole_owner, "整句嵌入", {})

    # 策略二：分片嵌入。
    chunk_owner = "chunkthr-chunk"
    reset_scope(collection_id, chunk_owner)
    chunk_documents: list[str] = []
    chunk_to_parent: dict[str, str] = {}
    for memory in corpus:
        for clause in split_clauses(memory):
            chunk_documents.append(clause)
            chunk_to_parent[clause] = memory
    write_records(collection_id, chunk_owner, chunk_documents, "chunk")

    print()
    print("=" * 74)
    print("【策略二】分片嵌入")
    print("=" * 74)
    chunk = evaluate(collection_id, chunk_owner, "分片嵌入", chunk_to_parent)

    print()
    print("=" * 74)
    print("【结论】")
    print("=" * 74)
    print(f"整句：区间 ({whole['lower']:.4f}, {whole['upper']:.4f}]  "
          f"宽度 {whole['upper'] - whole['lower']:.4f}")
    print(f"分片：区间 ({chunk['lower']:.4f}, {chunk['upper']:.4f}]  "
          f"宽度 {chunk['upper'] - chunk['lower']:.4f}")
    print()
    if chunk["separable"] and chunk["upper"] > whole["upper"]:
        print("=> 分片嵌入把长记忆的得分推到了更高区间，")
        print("   新的相关性下限应取分片区间的中点。")
    elif chunk["separable"]:
        print("=> 分片嵌入可分，但答对时的最低得分没有提升。")
    else:
        print("=> 分片嵌入也不可分。")

    reset_scope(collection_id, whole_owner)
    reset_scope(collection_id, chunk_owner)


if __name__ == "__main__":
    main()
