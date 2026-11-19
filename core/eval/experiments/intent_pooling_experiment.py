"""一次性实验：比较 CLS 与均值池化对**意图分类**准确率的影响。

为什么要做这个实验
------------------
嵌入服务当前用 CLS 池化，注释里写着"实测 CLS 在中文短句上的判别力优于均值池化"。
但那条结论来自**意图原型分类**场景，不能直接套到**记忆召回**场景：
记忆召回实测下来，均值池化的 Top-1 正确率更高（12/13 对 11/13）。

嵌入服务是**同一个进程、同一个模型**，池化方式对两个场景是全局选择。
所以改池化之前必须先确认：它不会把意图分类改差。

做法：按生产代码 PrototypeIntentClassifier 的方式，
用各自意图的示例句算原型向量（均值并归一化），
再对 15 条评测查询句取余弦最近的原型，比较两种池化的准确率。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
EMBEDDING_DIR = REPO_ROOT / "core" / "models" / "embedding"

# 意图示例句。与 core/cloud 的 IntentSamples 完全一致（逐字抄录）。
INTENT_SAMPLES: dict[str, list[str]] = {
    "set_volume": [
        "把音量调到五十", "声音大一点", "把声音调小一点",
        "音量再高一些", "太吵了，声音小点", "帮我把声音调大",
    ],
    "stop_speaking": [
        "别说了", "停止说话", "闭嘴别念了",
        "安静一点", "你能别念了吗", "先别说了",
    ],
    "play_music": [
        "放首音乐", "播放一首歌", "来首歌听听",
        "放音乐吧", "给我来点音乐", "换首歌",
    ],
    "check_time": ["现在几点了", "看一下时间", "现在什么时间", "报时"],
    "weather_query": [
        "今天天气怎么样", "外面下雨吗", "查询天气",
        "明天天气如何", "外面冷不冷",
    ],
    "check_device_status": [
        "看看电量", "设备状态如何", "还能用多久",
        "是不是快没电了", "你现在的状态怎么样",
    ],
    "emotional_support": [
        "我今天心情不好", "最近很焦虑", "我觉得很难过",
        "我有点累", "今天很不顺心", "我感到孤独",
    ],
    "chitchat": [
        "你好呀", "在忙什么呢", "陪我聊会儿天",
        "今天天气不错", "你叫什么名字",
    ],
}

# 评测查询句与期望意图。与 core/eval/intent-eval.txt 保持一致。
EVAL_PATH = REPO_ROOT / "core" / "eval" / "intent-eval.txt"


def load_eval() -> list[tuple[str, str]]:
    samples: list[tuple[str, str]] = []
    with open(EVAL_PATH, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            parts = line.split("|")
            if len(parts) < 3:
                continue
            samples.append((parts[1], parts[2]))
    return samples


def embed_all(texts: list[str], pooling: str) -> np.ndarray:
    import onnxruntime as ort
    from tokenizers import Tokenizer

    tokenizer = Tokenizer.from_file(str(EMBEDDING_DIR / "tokenizer.json"))
    session = ort.InferenceSession(
        str(EMBEDDING_DIR / "model.onnx"), providers=["CPUExecutionProvider"]
    )
    vectors = []
    for text in texts:
        encoding = tokenizer.encode(text)
        input_ids = np.array([encoding.ids], dtype=np.int64)
        attention_mask = np.ones_like(input_ids)
        outputs = session.run(
            None,
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "token_type_ids": np.zeros_like(input_ids),
            },
        )
        hidden = outputs[0][0]
        vector = hidden[0] if pooling == "cls" else hidden.mean(axis=0)
        norm = float(np.linalg.norm(vector))
        vectors.append(vector / norm if norm > 0 else vector)
    return np.array(vectors)


def main() -> int:
    eval_samples = load_eval()

    # 按意图分组示例句，一次批量嵌入。
    all_sample_texts: list[str] = []
    intent_ranges: list[tuple[str, int, int]] = []
    for intent, sentences in INTENT_SAMPLES.items():
        start = len(all_sample_texts)
        all_sample_texts.extend(sentences)
        intent_ranges.append((intent, start, len(all_sample_texts)))

    queries = [query for query, _ in eval_samples]
    expectations = [intent for _, intent in eval_samples]

    for pooling in ("cls", "mean"):
        sample_vectors = embed_all(all_sample_texts, pooling)
        query_vectors = embed_all(queries, pooling)

        prototypes: list[tuple[str, np.ndarray]] = []
        for intent, start, end in intent_ranges:
            mean = sample_vectors[start:end].mean(axis=0)
            norm = float(np.linalg.norm(mean))
            prototypes.append((intent, mean / norm if norm > 0 else mean))

        correct = 0
        wrong: list[str] = []
        for index, expected in enumerate(expectations):
            scores = [(float(query_vectors[index] @ vector), intent)
                      for intent, vector in prototypes]
            scores.sort(key=lambda item: item[0], reverse=True)
            predicted = scores[0][1]
            if predicted == expected:
                correct += 1
            else:
                wrong.append(f"{queries[index]} 期望={expected} 实际={predicted} "
                             f"(相似度 {scores[0][0]:.3f})")
        total = len(expectations)
        print(f"池化={pooling}: 意图准确率 {correct}/{total} = {correct / total * 100:.1f}%")
        for item in wrong:
            print(f"    错判: {item}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
