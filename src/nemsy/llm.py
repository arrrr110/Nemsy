"""DeepSeek LLM 封装模块。

使用 openai 库调用 DeepSeek API（OpenAI 兼容接口）。
支持流式输出、普通输出，以及 chat / reasoning 两种模型切换。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal

from openai import AsyncOpenAI

from nemsy.config import settings

# 消息类型别名
Message = dict[str, str]
Role = Literal["system", "user", "assistant"]


def _client() -> AsyncOpenAI:
    """创建 AsyncOpenAI 客户端（每次调用共享同一实例通过模块级缓存）。"""
    return AsyncOpenAI(
        api_key=settings.llm.api_key,
        base_url=settings.llm.base_url,
    )


# 模块级客户端单例（延迟初始化）
_openai_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    """获取全局 AsyncOpenAI 客户端单例。"""
    global _openai_client
    if _openai_client is None:
        _openai_client = _client()
    return _openai_client


def build_messages(
    system_prompt: str,
    history: list[Message],
    user_input: str,
) -> list[Message]:
    """构建发送给 LLM 的消息列表。

    Args:
        system_prompt: 系统提示词。
        history: 历史对话消息列表（[{"role": ..., "content": ...}, ...]）。
        user_input: 当前用户输入。
    Returns:
        完整的消息列表。
    """
    messages: list[Message] = [{"role": "system", "content": system_prompt}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_input})
    return messages


async def chat(
    messages: list[Message],
    *,
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> str:
    """非流式对话调用，返回完整回复文本。

    Args:
        messages: 消息列表。
        model: 模型名，默认使用 settings.llm.default_model。
        max_tokens: 最大输出 token，默认使用 settings.llm.max_tokens。
        temperature: 温度，默认使用 settings.llm.temperature。
    Returns:
        LLM 回复文本。
    """
    response = await get_client().chat.completions.create(
        model=model or settings.llm.default_model,
        messages=messages,  # type: ignore[arg-type]
        max_tokens=max_tokens or settings.llm.max_tokens,
        temperature=temperature if temperature is not None else settings.llm.temperature,
        stream=False,
    )
    return response.choices[0].message.content or ""


async def chat_stream(
    messages: list[Message],
    *,
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> AsyncIterator[str]:
    """流式对话调用，异步生成回复文本片段。

    Args:
        messages: 消息列表。
        model: 模型名，默认使用 settings.llm.default_model。
        max_tokens: 最大输出 token。
        temperature: 温度。
    Yields:
        逐块返回的文本片段。
    """
    stream = await get_client().chat.completions.create(
        model=model or settings.llm.default_model,
        messages=messages,  # type: ignore[arg-type]
        max_tokens=max_tokens or settings.llm.max_tokens,
        temperature=temperature if temperature is not None else settings.llm.temperature,
        stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


async def reason(
    messages: list[Message],
    *,
    max_tokens: int | None = None,
) -> str:
    """使用 deepseek-reasoner 进行深度推理，返回完整回复。

    适用于需要综合多文档、复杂分析的场景。

    Args:
        messages: 消息列表。
        max_tokens: 最大输出 token。
    Returns:
        LLM 回复文本。
    """
    return await chat(
        messages,
        model=settings.llm.reasoning_model,
        max_tokens=max_tokens,
        temperature=0.0,  # reasoning 模型固定低温度
    )
