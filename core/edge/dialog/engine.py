"""端侧本地对话引擎。

两条路径：

- **小模型**（llama-cpp）—— 正常路径，能结合上下文生成贴合的回复。
- **话术库** —— 降级路径。模型缺失、加载失败、或推理异常时自动接管。

关键约定：**引擎的创建与生成都不向调用方抛异常**。端侧对话是整条链路的
最后一环，此处崩溃会让用户看到"设备没反应"，而回落一句话术至少还有回应。
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Protocol

from core.edge.dialog.phrases import DEFAULT_EMOTION, PHRASES


class LocalDialogEngine(Protocol):
    """端侧本地对话引擎契约。"""

    def generate(self, emotion: str, context: str) -> str:
        """生成一句回复。

        @param emotion 情感标签
        @param context 上下文（用户刚说的话）
        @return 回复文本
        """
        ...


class PhraseBankDialogEngine:
    """话术库引擎。"""

    def __init__(self, phrases: dict[str, tuple[str, ...]] = PHRASES) -> None:
        """构造话术库引擎。

        @param phrases 情感标签到候选句的映射
        """
        self._phrases = phrases

    def generate(self, emotion: str, context: str) -> str:
        """从话术库随机取一句。

        @param emotion 情感标签
        @param context 上下文，不作使用
        @return 回复文本
        """
        candidates = self._phrases.get(emotion) or self._phrases.get(DEFAULT_EMOTION)
        if not candidates:
            return ""
        return random.choice(candidates)


class LlamaCppDialogEngine:
    """基于 llama.cpp 的本地生成引擎。"""

    def __init__(self, model_path: Path) -> None:
        """加载本地模型。

        @param model_path GGUF 模型文件路径
        @throws RuntimeError 模型文件缺失或加载失败时抛出
        """
        if not model_path.exists():
            raise RuntimeError(
                f"端侧模型文件不存在：{model_path}。"
                "请先执行 `core/scripts/fetch-models.ps1` 下载模型权重。"
            )
        try:
            from llama_cpp import Llama
        except ImportError as error:
            raise RuntimeError(
                "端侧对话需要 llama-cpp-python：请先执行 "
                "`pip install -r core/requirements.txt`"
            ) from error

        try:
            self._llama = Llama(model_path=str(model_path), n_ctx=2048, verbose=False)
        except Exception as error:
            raise RuntimeError(f"端侧模型加载失败：{error}") from error

    def generate(self, emotion: str, context: str) -> str:
        """生成一句回复。

        生成失败时回落到话术库，不向调用方抛异常。

        @param emotion 情感标签
        @param context 上下文
        @return 回复文本
        """
        prompt = (
            "你是用户的语音陪伴机器人，语气自然、简短，不超过两句话。\n"
            f"当前情感：{emotion}\n"
            f"用户说：{context}\n"
            "回复："
        )
        try:
            result = self._llama(prompt, max_tokens=64, temperature=0.7)
            text = (result["choices"][0]["text"] or "").strip()
        except Exception:
            return PhraseBankDialogEngine().generate(emotion, context)
        if not text:
            return PhraseBankDialogEngine().generate(emotion, context)
        return text


def create_dialog_engine(model_path: Path | None) -> LocalDialogEngine:
    """创建端侧对话引擎，模型不可用时自动回落到话术库。

    @param model_path GGUF 模型文件路径；为 None 表示不启用模型
    @return 对话引擎
    """
    if model_path is not None:
        try:
            return LlamaCppDialogEngine(model_path)
        except RuntimeError:
            # 模型缺失或加载失败：回落话术库，不打断整条链路。
            return PhraseBankDialogEngine()
    return PhraseBankDialogEngine()
