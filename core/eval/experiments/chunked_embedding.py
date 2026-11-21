"""验证"分片嵌入"能否解决长记忆被稀释的问题。

问题
----
一条记忆是完整句子（"我妈妈叫李芳，她很爱我，每天都给我做饭，还总提醒我早点休息"），
问句是短语（"我妈妈叫什么"）。
整句嵌入时，问句与长句的向量相距较远，得分落到相关性下限以下 → **误拒**。

假设
----
把长记忆**按分句切成多个片段**分别嵌入，
问句只需与其中**一个片段**（"我妈妈叫李芳"）相近 → 得分显著回升。

**这与"混合检索"是不同层次的手段**：
混合检索改变**候选排序**，分片嵌入改变**候选的表示**。
后者直接针对"稀释"的成因 —— 稀释发生在**向量层面**，排序层面救不回来。

跑法（仓库根目录，需先起 Chroma 与嵌入服务）：
    F:\\tools\\python313\\python.exe core\\eval\\experiments\\chunked_embedding.py
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
SCOPE_OWNER = "chunk-probe"

# 长记忆语料：真实对话里用户说的完整句子。
LONG_CORPUS = [
    "我妈妈叫李芳，她很爱我，每天都给我做饭，还总提醒我早点休息",
    "我表姐在南京工作，做建筑设计，平日里项目都挺忙的",
    "我每周三晚上都去健身房，练的是自由泳，已经坚持两年多了",
    "我的车是白色的，是辆小型的两厢车，平时主要在市区里通勤",
    "我养了三只仓鼠，一只叫团子一只叫糯米还有一只叫芝麻",
    "我奶奶住在苏州老家那边，小院子种了桂花，秋天的时候特别香",
]

# 问句与期望命中的片段。
ANSWERABLE = [
    ("我妈妈叫什么", "我妈妈叫李芳，她很爱我，每天都给我做饭，还总提醒我早点休息"),
    ("我表姐在哪里工作", "我表姐在南京工作，做建筑设计，平日里项目都挺忙的"),
    ("我什么时候去健身", "我每周三晚上都去健身房，练的是自由泳，已经坚持两年多了"),
    ("我的车是什么颜色", "我的车是白色的，是辆小型的两厢车，平时主要在市区里通勤"),
    ("我奶奶住在哪", "我奶奶住在苏州老家那边，小院子种了桂花，秋天的时候特别香"),
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


def split_clauses(sentence: str) -> list[str]:
    """把一句话按中文标点切成子句。

    **为什么这样切**：中文的并列信息天然以逗号分隔
    （"我妈妈叫李芳，她很爱我，每天都给我做饭"），
    每个子句承载一个独立事实。问句只会命中其中最相关的那一个。

    @param sentence 原句
    @return 子句列表；无法切分时返回原句
    """
    separators = ["，", ",", "、", "；", ";"]
    parts = [sentence]
    for separator in separators:
        expanded: list[str] = []
        for part in parts:
            expanded.extend(part.split(separator))
        parts = expanded
    clauses = [part.strip() for part in parts if part.strip()]
    return clauses if clauses else [sentence]


def main() -> None:
    """执行分片嵌入可行性验证。"""
    collection_id = resolve_collection_id()
    reset_scope(collection_id)

    # 每条长记忆拆成若干片段，逐片段嵌入、逐片段入库。
    chunk_owner = f"{SCOPE_OWNER}-chunk"
    chunk_where = {
        "$and": [
            {"scope_tenant": {"$eq": SCOPE_TENANT}},
            {"scope_owner": {"$eq": chunk_owner}},
        ]
    }
    request_json(f"{collections_url()}/{collection_id}/delete", {"where": chunk_where})

    # 对照组：整句记忆写入**对照组作用域**。
    whole_owner = f"{SCOPE_OWNER}-whole"
    whole_where = {
        "$and": [
            {"scope_tenant": {"$eq": SCOPE_TENANT}},
            {"scope_owner": {"$eq": whole_owner}},
        ]
    }
    request_json(f"{collections_url()}/{collection_id}/delete", {"where": whole_where})
    whole_vectors = embed(LONG_CORPUS)
    request_json(
        f"{collections_url()}/{collection_id}/add",
        {
            "ids": [f"whole-{index}" for index in range(len(LONG_CORPUS))],
            "embeddings": whole_vectors,
            "documents": LONG_CORPUS,
            "metadatas": [
                {
                    "scope_tenant": SCOPE_TENANT,
                    "scope_owner": whole_owner,
                    "weight": 1.0,
                    "created_at": 1_000_000 + index,
                    "archived": False,
                }
                for index in range(len(LONG_CORPUS))
            ],
        },
    )

    chunk_texts: list[str] = []
    chunk_owner_of: list[str] = []
    for memory in LONG_CORPUS:
        for clause in split_clauses(memory):
            chunk_texts.append(clause)
            chunk_owner_of.append(memory)

    vectors = embed(chunk_texts)
    request_json(
        f"{collections_url()}/{collection_id}/add",
        {
            "ids": [f"chunk-{index}" for index in range(len(chunk_texts))],
            "embeddings": vectors,
            "documents": chunk_texts,
            "metadatas": [
                {
                    "scope_tenant": SCOPE_TENANT,
                    "scope_owner": chunk_owner,
                    "weight": 1.0,
                    "created_at": 1_000_000 + index,
                    "archived": False,
                }
                for index in range(len(chunk_texts))
            ],
        },
    )

    def query_chunks(text: str, top_k: int = 5) -> list[tuple[str, float]]:
        """查询分片集合。

        @param text 查询文本
        @param top_k 条数上限
        @return (片段, 得分) 列表
        """
        vector = embed([text])[0]
        body = request_json(
            f"{collections_url()}/{collection_id}/query",
            {
                "query_embeddings": [vector],
                "n_results": top_k,
                "include": ["documents", "distances"],
                "where": chunk_where,
            },
        )
        return [
            (document, 1.0 / (1.0 + distance))
            for document, distance in zip(body["documents"][0], body["distances"][0])
        ]

    def query_whole(text: str, top_k: int = 5) -> list[tuple[str, float]]:
        """查询整句集合（对照组）。

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
                "where": whole_where,
            },
        )
        return [
            (document, 1.0 / (1.0 + distance))
            for document, distance in zip(body["documents"][0], body["distances"][0])
        ]

    print("=" * 74)
    print("【对照组】整句嵌入")
    print("=" * 74)
    whole_answerable: list[float] = []
    whole_unanswerable: list[float] = []
    whole_wrong = 0
    for question, expected in ANSWERABLE:
        hits = query_whole(question)
        if not hits:
            continue
        top_document, top_score = hits[0]
        matched = top_document == expected
        if not matched:
            whole_wrong += 1
        print(f"  {'OK ' if matched else '!! '}{question}   得分={top_score:.4f}")
        whole_answerable.append(top_score)
    for question in UNANSWERABLE:
        hits = query_whole(question)
        score = hits[0][1] if hits else -1.0
        whole_unanswerable.append(score)
        print(f"      {question}   最高得分={score:.4f}")

    print()
    print("=" * 74)
    print("【实验组】分片嵌入")
    print("=" * 74)
    chunk_answerable: list[float] = []
    chunk_unanswerable: list[float] = []
    chunk_wrong = 0
    for question, expected in ANSWERABLE:
        hits = query_chunks(question)
        if not hits:
            continue
        top_chunk, top_score = hits[0]
        # 命中的片段必须属于期望的那条记忆，才算答对。
        matched = chunk_owner_of[chunk_texts.index(top_chunk)] == expected
        if not matched:
            chunk_wrong += 1
        print(f"  {'OK ' if matched else '!! '}{question}")
        print(f"      命中片段：{top_chunk}   得分={top_score:.4f}")
        chunk_answerable.append(top_score)
    for question in UNANSWERABLE:
        hits = query_chunks(question)
        score = hits[0][1] if hits else -1.0
        chunk_unanswerable.append(score)
        print(f"      {question}   最高得分={score:.4f}")

    print()
    print("=" * 74)
    print("【对比】")
    print("=" * 74)
    print(f"整句嵌入：答错 {whole_wrong} 条，答对时最低得分 = {min(whole_answerable):.4f}")
    print(f"分片嵌入：答错 {chunk_wrong} 条，答对时最低得分 = {min(chunk_answerable):.4f}")
    print()
    print(f"整句：无答案时最高得分 = {max(whole_unanswerable):.4f}")
    print(f"分片：无答案时最高得分 = {max(chunk_unanswerable):.4f}")

    whole_lower = max(whole_unanswerable)
    whole_upper = min(whole_answerable)
    chunk_lower = max(chunk_unanswerable)
    chunk_upper = min(chunk_answerable)
    print()
    print(f"整句可分区间：({whole_lower:.4f}, {whole_upper:.4f}]  "
          f"{'可分' if whole_lower < whole_upper else '不可分'}")
    print(f"分片可分区间：({chunk_lower:.4f}, {chunk_upper:.4f}]  "
          f"{'可分' if chunk_lower < chunk_upper else '不可分'}")
    if chunk_lower < chunk_upper:
        print(f"=> 分片可分，中点 {(chunk_lower + chunk_upper) / 2:.4f}")
    else:
        print("=> 分片也不可分")

    request_json(f"{collections_url()}/{collection_id}/delete", {"where": chunk_where})
    reset_scope(collection_id)


if __name__ == "__main__":
    main()
