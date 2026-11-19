"""测量检索的"噪声底"——同一事实的不同说法之间能拉开多少分。

为什么需要它
------------
记忆作答维度里有两类判定：

1. **相关性下限**：排第一的那条到底相不相关（全局阈值）；
2. **区分度**：排第一的那条与排第二条之间拉开了多少（相对阈值）。

第 2 类判定的阈值**不能靠"看数据挑一个能过线的数"来定** ——
13 条样本上挑出来的阈值，过拟合得厉害，换一批数据就失效。

这里用一个**不依赖评测集**的办法来定它：
把每条记忆事实**改写成另一种说法**（同义不同词），
再拿改写句去检索原句。若改写句都能被稳定地找回，
那么"排第一与排第二之间的分差"必须**大于这个改写带来的分差**，
否则系统根本分不清"找到了"与"找错了"。

换句话说：**改写带来的分差就是分辨力的噪声底**，
区分度阈值应当高于它。

跑法（在仓库根目录）：
    F:\\tools\\python313\\python.exe core\\eval\\experiments\\paraphrase_noise.py
"""

from __future__ import annotations

import json
import urllib.request

import numpy as np

EMBEDDING_BASE = "http://127.0.0.1:8766"

# 记忆原文 → 改写说法（同义不同表述）。
PARAPHRASES: list[tuple[str, str]] = [
    ("我奶奶住在苏州", "我奶奶的家在苏州"),
    ("我养了三只仓鼠", "我家养着三只小仓鼠"),
    ("我最爱吃酸菜鱼", "我最喜欢的一道菜是酸菜鱼"),
    ("我下个月要参加同学的婚礼", "下个月我得去参加同学生的婚礼"),
    ("我怕黑", "我最怕的是黑暗"),
    ("我习惯用左手写字", "我写字习惯用左手"),
    ("我表姐在南京工作", "我表姐上班的地方在南京"),
    ("我今年三十五岁", "我的年纪是三十五岁"),
    ("我每周三去健身房", "我一般周三都会去健身房"),
    ("我对芒果过敏", "芒果这个东西我吃了会过敏"),
    ("我岳父喜欢下棋", "我岳父平常爱下棋"),
    ("我的车是白色的", "我那辆车的颜色是白的"),
    ("我正在准备考研", "考研这件事我正在准备"),
]


def embed(texts: list[str]) -> list[list[float]]:
    """调用本地嵌入服务取向量。"""
    payload = json.dumps({"input": texts}).encode("utf-8")
    request = urllib.request.Request(
        f"{EMBEDDING_BASE}/v1/embeddings",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        body = json.loads(response.read().decode("utf-8"))
    return [item["embedding"] for item in body["data"]]


def normalized(vector: np.ndarray) -> np.ndarray:
    """L2 归一化。"""
    norm = np.linalg.norm(vector)
    return vector / norm if norm > 0 else vector


def main() -> None:
    """测量并打印噪声底。"""
    originals = [original for original, _ in PARAPHRASES]
    rewrites = [rewrite for _, rewrite in PARAPHRASES]

    original_vectors = [normalized(np.array(v)) for v in embed(originals)]
    rewrite_vectors = [normalized(np.array(v)) for v in embed(rewrites)]

    scores: list[float] = []
    print("=== 同一事实的改写与原句的得分 ===")
    for (original, rewrite), original_vector, rewrite_vector in zip(
        PARAPHRASES, original_vectors, rewrite_vectors
    ):
        distance = float(2.0 - 2.0 * np.dot(original_vector, rewrite_vector))
        score = 1.0 / (1.0 + distance)
        scores.append(score)
        print(f"  {original}")
        print(f"    改写: {rewrite}")
        print(f"    得分={score:.4f}  距离={distance:.4f}")

    print()
    print(f"改写得分最小值 = {min(scores):.4f}")
    print(f"改写得分中位数 = {float(np.median(scores)):.4f}")
    print(f"改写得分最大值 = {max(scores):.4f}")

    # 噪声底的定义：改写句与原句之间"看起来不像同一件事"的分差上界。
    #
    # 系统必须能把"同一事实的改写"与"另一件事"区分开。
    # 若改写句的得分能低到 X，那么任何低于 X 的候选都不该被当成答案 ——
    # 因为它可能只是"勉强沾边"。
    noise_floor = min(scores)
    print()
    print(f"=> 噪声底（改写得分下界）= {noise_floor:.4f}")
    print("=> 若把相关性下限定为噪声底，则只有改写后仍能被认出来的事实才会被作答。")


if __name__ == "__main__":
    main()
