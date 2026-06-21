"""DeepSeek LLM 封装模块（Anthropic 协议）。

使用 anthropic SDK 调用 DeepSeek API 的 Anthropic 兼容接口。
base_url: https://api.deepseek.com/anthropic

协议优势：
- 原生支持 Tool Calls（为后续 MCP 集成铺路）
- 原生支持 thinking 块（deepseek-v4-pro 深度推理）
- 与 Claude 生态完全兼容

支持：流式输出、普通输出、深度推理（thinking）三种调用模式。

Token 用量跟踪：
- chat() 返回 (text, TokenUsage)
- chat_stream() 返回 (AsyncIterator[str], TokenUsageFuture) —— 迭代完成后 .get() 可取 TokenUsage
- reason() 返回 (text, TokenUsage)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

import anthropic

from nemsy.config import settings

# 消息类型别名（Anthropic 格式）
Message = dict[str, str]


@dataclass
class TokenUsage:
    """单次 LLM 调用的 token 用量。"""

    prompt_tokens: int
    completion_tokens: int
    model: str

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @classmethod
    def zero(cls, model: str = "") -> "TokenUsage":
        return cls(prompt_tokens=0, completion_tokens=0, model=model)


# 模块级客户端单例（延迟初始化）
_anthropic_client: anthropic.AsyncAnthropic | None = None


def get_client() -> anthropic.AsyncAnthropic:
    """获取全局 AsyncAnthropic 客户端单例。

    API Key 优先级：DEEPSEEK_API_KEY（.env）> ANTHROPIC_API_KEY（环境变量）
    """
    global _anthropic_client
    if _anthropic_client is None:
        import os
        api_key = settings.llm.api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        _anthropic_client = anthropic.AsyncAnthropic(
            api_key=api_key,
            base_url=settings.llm.base_url,
        )
    return _anthropic_client


def build_messages(
    system_prompt: str,
    history: list[Message],
    user_input: str,
) -> tuple[str, list[dict]]:
    """构建发送给 LLM 的消息结构（Anthropic 格式）。

    Anthropic 协议中 system 是独立参数，不放在 messages 里。

    Args:
        system_prompt: 系统提示词。
        history: 历史对话消息列表。
        user_input: 当前用户输入。
    Returns:
        (system_prompt, messages) 元组。
    """
    messages: list[dict] = []
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_input})
    return system_prompt, messages


async def chat(
    system_prompt: str,
    messages: list[dict],
    *,
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> tuple[str, TokenUsage]:
    """非流式对话调用，返回完整回复文本和 token 用量。

    Args:
        system_prompt: 系统提示词。
        messages: 消息列表（不含 system）。
        model: 模型名，默认使用 settings.llm.default_model。
        max_tokens: 最大输出 token。
        temperature: 温度。
    Returns:
        (LLM 回复文本, TokenUsage) 元组。
    """
    _model = model or settings.llm.default_model
    response = await get_client().messages.create(
        model=_model,
        system=system_prompt,
        messages=messages,  # type: ignore[arg-type]
        max_tokens=max_tokens or settings.llm.max_tokens,
        temperature=temperature if temperature is not None else settings.llm.temperature,
    )
    text = _extract_text(response.content)
    usage = TokenUsage(
        prompt_tokens=response.usage.input_tokens,
        completion_tokens=response.usage.output_tokens,
        model=_model,
    )
    return text, usage


async def chat_stream(
    system_prompt: str,
    messages: list[dict],
    *,
    model: str | None = None,
    max_tokens: int | None = None,
    temperature: float | None = None,
) -> tuple[AsyncIterator[str], "_UsageBox"]:
    """流式对话调用，返回 (文本迭代器, 用量容器) 元组。

    迭代完成后通过 usage_box.usage 取 TokenUsage。

    Args:
        system_prompt: 系统提示词。
        messages: 消息列表。
        model: 模型名。
        max_tokens: 最大输出 token。
        temperature: 温度。
    Returns:
        (AsyncIterator[str], _UsageBox) 元组。
    """
    _model = model or settings.llm.default_model
    usage_box = _UsageBox(_model)

    async def _gen() -> AsyncIterator[str]:
        async with get_client().messages.stream(
            model=_model,
            system=system_prompt,
            messages=messages,  # type: ignore[arg-type]
            max_tokens=max_tokens or settings.llm.max_tokens,
            temperature=temperature if temperature is not None else settings.llm.temperature,
        ) as stream:
            async for text in stream.text_stream:
                yield text
            # 流结束后，从最终消息中提取 usage
            final_msg = await stream.get_final_message()
            usage_box.usage = TokenUsage(
                prompt_tokens=final_msg.usage.input_tokens,
                completion_tokens=final_msg.usage.output_tokens,
                model=_model,
            )

    return _gen(), usage_box


class _UsageBox:
    """流式调用结束后存放 TokenUsage 的容器。"""

    def __init__(self, model: str) -> None:
        self.usage: TokenUsage = TokenUsage.zero(model)


async def reason(
    system_prompt: str,
    messages: list[dict],
    *,
    max_tokens: int | None = None,
) -> tuple[str, TokenUsage]:
    """使用 deepseek-v4-pro 进行深度推理（thinking 模式）。

    适用于需要综合多文档、复杂分析的场景。
    thinking 块会被自动过滤，只返回最终回复文本。

    Args:
        system_prompt: 系统提示词。
        messages: 消息列表。
        max_tokens: 最大输出 token。
    Returns:
        (LLM 最终回复文本, TokenUsage) 元组（不含 thinking 过程）。
    """
    _model = settings.llm.reasoning_model
    response = await get_client().messages.create(
        model=_model,
        system=system_prompt,
        messages=messages,  # type: ignore[arg-type]
        max_tokens=max_tokens or settings.llm.max_tokens,
        temperature=1.0,  # thinking 模式要求 temperature=1
        thinking={"type": "enabled", "budget_tokens": 4096},  # type: ignore[arg-type]
    )
    text = _extract_text(response.content)
    usage = TokenUsage(
        prompt_tokens=response.usage.input_tokens,
        completion_tokens=response.usage.output_tokens,
        model=_model,
    )
    return text, usage


def _extract_text(content: list) -> str:
    """从 Anthropic 响应的 content 块列表中提取纯文本，跳过 thinking 块。"""
    parts: list[str] = []
    for block in content:
        if hasattr(block, "type"):
            if block.type == "text":
                parts.append(block.text)
            # thinking 块静默跳过
    return "".join(parts)


# ---------------------------------------------------------------------------
# 账户余额查询
# ---------------------------------------------------------------------------

def fetch_balance() -> dict:
    """同步查询 DeepSeek 账户余额，返回结构化 dict。

    返回格式::

        # 成功
        {"available": True, "total_balance": "10.00",
         "granted_balance": "0.00", "topped_up_balance": "10.00",
         "currency": "CNY"}

        # 失败
        {"available": False, "reason": "<原因字符串>"}

    reason 取值：
        "api_key_not_set"  — API Key 未配置
        "http_<code>"      — HTTP 状态码非 200
        "<异常信息>"        — 网络/解析异常
    """
    if not settings.llm.api_key:
        return {"available": False, "reason": "api_key_not_set"}
    try:
        import httpx
        resp = httpx.get(
            "https://api.deepseek.com/user/balance",
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {settings.llm.api_key}",
            },
            timeout=5.0,
        )
        if resp.status_code == 200:
            infos = resp.json().get("balance_infos", [])
            if infos:
                info = infos[0]
                return {
                    "available": True,
                    "total_balance": info.get("total_balance", "0"),
                    "granted_balance": info.get("granted_balance", "0"),
                    "topped_up_balance": info.get("topped_up_balance", "0"),
                    "currency": info.get("currency", "CNY"),
                }
            return {"available": True, "total_balance": "0", "currency": "CNY"}
        return {"available": False, "reason": f"http_{resp.status_code}"}
    except Exception as e:
        return {"available": False, "reason": str(e)[:120]}


async def fetch_balance_async() -> dict:
    """异步版余额查询（供 FastAPI 路由使用），底层逻辑与 fetch_balance() 相同。"""
    if not settings.llm.api_key:
        return {"available": False, "reason": "api_key_not_set"}
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                "https://api.deepseek.com/user/balance",
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {settings.llm.api_key}",
                },
            )
        if resp.status_code == 200:
            infos = resp.json().get("balance_infos", [])
            if infos:
                info = infos[0]
                return {
                    "available": True,
                    "total_balance": info.get("total_balance", "0"),
                    "granted_balance": info.get("granted_balance", "0"),
                    "topped_up_balance": info.get("topped_up_balance", "0"),
                    "currency": info.get("currency", "CNY"),
                }
            return {"available": True, "total_balance": "0", "currency": "CNY"}
        return {"available": False, "reason": f"http_{resp.status_code}"}
    except Exception as e:
        return {"available": False, "reason": str(e)[:120]}
