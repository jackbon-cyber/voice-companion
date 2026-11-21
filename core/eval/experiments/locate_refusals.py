"""定位记忆作答维度里被拒答的具体条目。

**为什么需要这个脚本**：评测报告只给"10 条作答 / 15 条适用"这样的汇总，
但**哪 3 条被拒**才是改进的抓手。
本脚本按与生产链路完全一致的口径（同一份评测集、同一套阈值、
同一套相关性准入策略）逐条复算，把被拒的条目与它们的得分列出来。

**口径必须与生产一致**：
- 记忆原文按中文标点分片后入库（与 ChromaLongTermStore 一致）；
- 召回取 Top-5；
- 按 MemoryRelevancePolicy 的规则选出一条（得分下限 0.544）。

跑法（仓库根目录，需先起 Chroma 与嵌入服务）：
    F:\\tools\\python313\\python.exe core\\eval\\experiments\\locate_refusals.py
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
SCOPE_TENANT = "evaluation"
SCOPE_OWNER = "refusal-probe"

# 与 MemoryRelevancePolicy.MIN_RELEVANCE_SCORE 保持一致。
RELEVANCE_THRESHOLD = 0.544

# 召回条数上限，与 MemoryGroundedReplyService.RECALL_LIMIT 一致。
TOP_K = 5

# 分片规则，与 MemoryChunkSplitter 保持一致。
SEPARATORS = ["，", ",", "、", "；", ";"]
MIN_CHUNK_LENGTH = 3
MAX_SINGLE_CHUNK_LENGTH = 12

EVAL_FILE = "core/eval/memory_answer-eval.txt"


def request_json(url: str, payload: dict | None = None, method: str = "POST") -> object:
    """发起一次 JSON 请求。

    @param url 地址
    @param payload 请求体
    @param method 方法
    @return 响应内容
    """
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
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
            {"archived": {"$eq": False}},
        ]
    }


def reset_scope(collection_id: str) -> None:
    """清空本脚本的作用域。

    @param collection_id 集合 id
    """
    request_json(f"{collections_url()}/{collection_id}/delete", {"where": scope_where()})


def split_clauses(sentence: str) -> list[str]:
    """按中文标点切分记忆（与 MemoryChunkSplitter 一致）。

    @param sentence 原句
    @return 片段列表
    """
    if len(sentence) <= MAX_SINGLE_CHUNK_LENGTH:
        return [sentence]
    parts = [sentence]
    for separator in SEPARATORS:
        expanded: list[str] = []
        for part in parts:
            expanded.extend(part.split(separator))
        parts = expanded
    chunks = [part.strip() for part in parts if len(part.strip()) >= MIN_CHUNK_LENGTH]
    return chunks if len(chunks) > 1 else [sentence]


def write_memories(collection_id: str, memories: list[str]) -> None:
    """把记忆按分片写入。

    @param collection_id 集合 id
    @param memories 记忆原文列表
    """
    documents: list[str] = []
    parents: list[str] = []
    for memory in memories:
        for chunk in split_clauses(memory):
            documents.append(chunk)
            parents.append(memory)

    vectors = embed(documents)
    request_json(
        f"{collections_url()}/{collection_id}/add",
        {
            "ids": [f"refusal-{index}" for index in range(len(documents))],
            "embeddings": vectors,
            "documents": documents,
            "metadatas": [
                {
                    "scope_tenant": SCOPE_TENANT,
                    "scope_owner": SCOPE_OWNER,
                    "weight": 1.0,
                    "created_at": 1_000_000 + index,
                    "archived": False,
                    "parent_content": parents[index],
                }
                for index in range(len(documents))
            ],
        },
    )


def query(collection_id: str, question: str) -> list[tuple[str, float]]:
    """检索并按父记忆去重，返回 (父记忆正文, 最高得分)。

    @param collection_id 集合 id
    @param question 问句
    @return (父记忆正文, 得分) 列表
    """
    vector = embed([question])[0]
    body = request_json(
        f"{collections_url()}/{collection_id}/query",
        {
            "query_embeddings": [vector],
            "n_results": TOP_K,
            "include": ["documents", "distances", "metadatas"],
            "where": scope_where(),
        },
    )
    documents = body["documents"][0]
    distances = body["distances"][0]
    metadatas = body["metadatas"][0]

    best: dict[str, tuple[str, float]] = {}
    for index in range(len(documents)):
        metadata = metadatas[index]
        parent = metadata.get("parent_content") or documents[index]
        score = 1.0 / (1.0 + distances[index])
        if parent not in best or score > best[parent][1]:
            best[parent] = (parent, score)
    return sorted(best.values(), key=lambda item: item[1], reverse=True)


def load_samples() -> list[tuple[str, str, str]]:
    """读取记忆作答评测集。

    @return (问句, 期望, 记忆原文) 列表；期望拒答的记忆原文为空
    """
    samples: list[tuple[str, str, str]] = []
    with open(EVAL_FILE, encoding="utf-8") as handle:
        for line in handle:
            trimmed = line.strip()
            if not trimmed or trimmed.startswith("#"):
                continue
            parts = trimmed.split("|")
            if len(parts) < 3:
                continue
            question = parts[1]
            expected = parts[2]
            corpus = parts[3] if len(parts) > 3 else ""
            samples.append((question, expected, corpus))
    return samples


def main() -> None:
    """逐条复算，列出被拒答的条目。"""
    samples = load_samples()
    answerable = [item for item in samples if item[1] == "ANSWERED"]
    memories = [item[2] for item in answerable if item[2]]

    collection_id = resolve_collection_id()
    reset_scope(collection_id)
    write_memories(collection_id, memories)

    print("=" * 76)
    print("【期望作答的条目】")
    print("=" * 76)
    refused: list[tuple[str, str, float]] = []
    answered = 0
    for question, _expected, corpus in answerable:
        hits = query(collection_id, question)
        top_content, top_score = hits[0] if hits else ("", -1.0)
        admitted = top_score >= RELEVANCE_THRESHOLD
        correct = admitted and top_content == corpus
        if correct:
            answered += 1
            print(f"  OK  {question}   得分={top_score:.4f}")
        else:
            refused.append((question, corpus, top_score))
            print(f"  !!  {question}")
            print(f"      期望 {corpus}")
            print(f"      实际 {top_content}   得分={top_score:.4f}")

    print()
    print("=" * 76)
    print("【期望拒答的条目】")
    print("=" * 76)
    fabricated = 0
    for question, _expected, _corpus in [item for item in samples if item[1] == "REFUSED"]:
        hits = query(collection_id, question)
        top_content, top_score = hits[0] if hits else ("", -1.0)
        admitted = top_score >= RELEVANCE_THRESHOLD
        if admitted:
            fabricated += 1
            print(f"  !!  {question}   得分={top_score:.4f}  (期望拒答却作答了)")
        else:
            print(f"  OK  {question}   最高得分={top_score:.4f}  (正确拒答)")

    print()
    print("=" * 76)
    print("【汇总】")
    print("=" * 76)
    print(f"作答准确率 = {answered}/{len(answerable)} = "
          f"{answered / max(1, len(answerable)) * 100:.1f}%")
    print(f"作答率     = {answered}/{len(answerable)} = "
          f"{answered / max(1, len(answerable)) * 100:.1f}%")
    print(f"编造率     = {fabricated}/{len(samples) - len(answerable)} = "
          f"{fabricated / max(1, len(samples) - len(answerable)) * 100:.1f}%")
    print()
    if refused:
        print("被拒答的条目（改进抓手）：")
        for question, corpus, score in refused:
            gap = RELEVANCE_THRESHOLD - score
            print(f"  - {question}  期望={corpus}  得分={score:.4f}  距阈值差 {gap:.4f}")

    reset_scope(collection_id)


if __name__ == "__main__":
    main()
