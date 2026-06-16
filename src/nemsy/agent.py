"""Nemsy Agent 核心模块。

实现三大核心操作：
- ingest：摄取新资料，整合进 Wiki
- query：向 Wiki 提问，生成综合答案
- lint：对 Wiki 进行健康检查
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console

from nemsy import llm
from nemsy.config import settings
from nemsy.vault import (
    Note,
    append_log,
    append_wiki_note,
    list_wiki_notes,
    read_wiki_note,
    write_wiki_note,
)

console = Console()

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_BASE_SYSTEM = """你是 Nemsy，一个由 DeepSeek 驱动的个人知识助手。
你负责维护用户的 Obsidian Wiki 知识库。
Wiki 目录：{wiki_path}

你遵循以下原则：
1. 知识积累优先：每次摄取新资料都要更新相关 Wiki 页面，不只是生成摘要
2. 交叉引用：若内容与已有 Wiki 页面有明确关联，用 [[页面名]] 标注；无需强行寻找关联
3. 矛盾标注：用 > ⚠️ 矛盾 格式标注与已有知识相悖的内容
4. 简洁精确：摘要简洁，关键信息不遗漏
5. 中文优先：所有 Wiki 内容用中文撰写，专业术语保留英文
"""

_INGEST_SYSTEM = (
    _BASE_SYSTEM
    + """
当前任务：摄取新资料并整合进 Wiki。

工作流程：
1. 仔细阅读提供的资料内容
2. 提取关键信息、核心观点、重要实体
3. 生成结构化摘要页面（包含 frontmatter：title, date, source, tags）
4. 列出需要更新的现有 Wiki 页面及更新内容
5. 提出该资料引发的值得深究的问题

链接规范（重要）：
- Wiki 内部链接只写文件名，不写路径，格式：[[文件名]]
- 例如：[[极简主义金融改革模型]] 而不是 [[concepts/极简主义金融改革模型.md]]
- Obsidian 会自动根据文件名匹配，无需写完整路径

输出格式：
---SUMMARY---
[摘要页面的完整 Markdown 内容，含 frontmatter]
---UPDATES---
[需要更新的页面列表，每条格式：文件名 | 更新内容]
---QUESTIONS---
[值得进一步探究的问题列表]
"""
)

_QUERY_SYSTEM = (
    _BASE_SYSTEM
    + """
当前任务：基于 Wiki 内容回答用户问题。

工作流程：
1. 理解用户问题
2. 在提供的 Wiki 内容中检索相关信息
3. 综合多个页面的内容给出答案
4. 在答案末尾列出引用来源（[[页面名]] 格式）
5. 如果答案本身有归档价值，在末尾标注 ARCHIVABLE: true

回答要直接、有深度，不要泛泛而谈。
"""
)

_LINT_SYSTEM = (
    _BASE_SYSTEM
    + """
当前任务：对 Wiki 进行健康检查。

检查项目：
1. 页面间的逻辑矛盾
2. 被新资料推翻的过时观点
3. 没有入站链接的孤立页面（orphan）
4. 被多次提及但缺少独立页面的重要概念
5. 缺失的交叉引用
6. 可以通过外部搜索补充的数据空白

输出格式：
---ISSUES---
[发现的问题列表，每条说明：类型 | 涉及页面 | 问题描述]
---SUGGESTIONS---
[建议新建的页面或需要补充的内容]
---NEXT_SOURCES---
[建议寻找的新资料方向]
"""
)


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _load_wiki_context(max_files: int = 30) -> str:
    """加载 Wiki 页面内容作为上下文，优先加载 index.md 和最近修改的页面。"""
    wiki_files = list_wiki_notes()
    if not wiki_files:
        return "（Wiki 目前为空）"

    context_parts: list[str] = []

    # 优先加载 index.md
    index_path = settings.vault.wiki_path / settings.vault.wiki_index_file
    if index_path.exists():
        context_parts.append(f"=== {settings.vault.wiki_index_file} ===\n{index_path.read_text(encoding='utf-8')}")

    # 按修改时间倒序加载其余页面
    _skip = {settings.vault.wiki_index_file, settings.vault.wiki_log_file}
    other_files = [f for f in wiki_files if f.name not in _skip]
    other_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    for f in other_files[:max_files]:
        rel = f.relative_to(settings.vault.wiki_path)
        content = f.read_text(encoding="utf-8")
        context_parts.append(f"=== {rel} ===\n{content}")

    return "\n\n".join(context_parts)


def _update_index(title: str, filename: str, summary_line: str) -> None:
    """更新 Wiki 的 index.md，追加新条目。"""
    from datetime import date

    index_file = settings.vault.wiki_index_file
    entry = f"- [[{filename.removesuffix('.md')}]] — {summary_line} （{date.today()}）\n"
    index_content = read_wiki_note(index_file)

    if index_content is None:
        # 首次创建 index.md
        write_wiki_note(
            index_file,
            f"# Nemsy Wiki 索引\n\n## 最近添加\n\n{entry}",
            metadata={"title": "Wiki 索引", "auto_generated": True},
        )
    else:
        append_wiki_note(index_file, entry)


# ---------------------------------------------------------------------------
# 三大核心操作
# ---------------------------------------------------------------------------

async def ingest(
    source_content: str,
    source_title: str,
    *,
    source_path: Path | None = None,
    ingest_mode: str = "full",
    stream: bool = True,
) -> str | None:
    """摄取新资料，整合进 Wiki。

    Args:
        source_content: 资料的完整文本内容。
        source_title: 资料标题（用于命名摘要页面和日志）。
        source_path: 原始文件绝对路径，用于写入 ingest_log；为 None 时跳过 log 写入。
        ingest_mode: 摄取模式，"quick" 或 "full"。
        stream: 是否流式输出到控制台。
    Returns:
        生成的 Wiki 摘要页相对路径（如 "sources/xxx-2026-06-12.md"），失败时返回 None。
    """
    from nemsy.vault import record_ingest

    wiki_context = _load_wiki_context()
    user_prompt = f"""请处理以下资料：

标题：{source_title}

---资料内容---
{source_content}

---当前 Wiki 状态---
{wiki_context}
"""
    system, messages = llm.build_messages(_INGEST_SYSTEM.format(wiki_path=settings.vault.wiki_path), [], user_prompt)

    if stream:
        console.print(f"\n[cyan]Nemsy 正在摄取：{source_title}[/cyan]\n")
        full_response = ""
        async for chunk in llm.chat_stream(system, messages):
            console.print(chunk, end="", markup=False)
            full_response += chunk
        console.print()
    else:
        full_response = await llm.chat(system, messages)

    # 解析并写入摘要页面，获取生成的 wiki_page 路径
    wiki_page = _parse_and_write_ingest(full_response, source_title)
    append_log("ingest", source_title)

    # 写入 ingest_log（含 hash、ingest_mode、wiki_page）
    if source_path is not None:
        record_ingest(source_path, source_content, ingest_mode=ingest_mode, wiki_page=wiki_page)

    return wiki_page


def _parse_and_write_ingest(response: str, source_title: str) -> str | None:
    """解析 ingest 响应，写入 Wiki 摘要页面并更新相关页面。

    Returns:
        生成的摘要页相对路径（如 "sources/xxx-2026-06-12.md"），未生成时返回 None。
    """
    import re
    from datetime import date

    wiki_page: str | None = None

    # 提取 SUMMARY 部分
    summary_match = re.search(r"---SUMMARY---\n(.*?)(?=---UPDATES---|---QUESTIONS---|$)", response, re.DOTALL)
    if summary_match:
        summary_content = summary_match.group(1).strip()

        # 去除 LLM 可能包裹的 ```markdown ... ``` 代码块
        code_block_match = re.match(r"^```(?:markdown)?\s*\n(.*?)\n```\s*$", summary_content, re.DOTALL)
        if code_block_match:
            summary_content = code_block_match.group(1).strip()

        safe_title = re.sub(r'[^\w\u4e00-\u9fff\-_ ]', '', source_title).strip().replace(" ", "-")
        filename = f"{settings.vault.wiki_sources_dir}/{safe_title}-{date.today()}.md"

        # 直接写入原始文本，避免经过 frontmatter.Post 二次序列化导致格式破坏
        wiki_path = settings.vault.wiki_path
        file_path = wiki_path / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(summary_content, encoding="utf-8")

        _update_index(source_title, filename, f"来自 {source_title} 的摘要")
        console.print(f"\n[green]✓ 摘要已写入：{filename}[/green]")
        wiki_page = filename

    # 提取 UPDATES 部分并展示（实际更新由用户确认后执行）
    updates_match = re.search(r"---UPDATES---\n(.*?)(?=---QUESTIONS---|$)", response, re.DOTALL)
    if updates_match:
        updates_text = updates_match.group(1).strip()
        if updates_text:
            console.print(f"\n[yellow]需要更新的 Wiki 页面：[/yellow]\n{updates_text}")

    return wiki_page


async def query(question: str, *, stream: bool = True, archive: bool = False) -> str:
    """向 Wiki 提问，生成综合答案。

    Args:
        question: 用户问题。
        stream: 是否流式输出。
        archive: 是否将答案归档为新 Wiki 页面。
    Returns:
        LLM 的完整回复文本。
    """
    wiki_context = _load_wiki_context()
    user_prompt = f"""问题：{question}

    ---Wiki 内容---
    {wiki_context}
    """
    system, messages = llm.build_messages(_QUERY_SYSTEM.format(wiki_path=settings.vault.wiki_path), [], user_prompt)

    if stream:
        console.print(f"\n[cyan]Nemsy 正在思考：{question}[/cyan]\n")
        full_response = ""
        async for chunk in llm.chat_stream(system, messages):
            console.print(chunk, end="", markup=False)
            full_response += chunk
        console.print()
    else:
        full_response = await llm.chat(system, messages)

    # 检查是否建议归档
    if archive or "ARCHIVABLE: true" in full_response:
        _archive_query_result(question, full_response)

    append_log("query", question, detail=f"归档：{'是' if archive else '否'}")
    return full_response


def _archive_query_result(question: str, answer: str) -> None:
    """将查询结果归档为 Wiki 页面。"""
    import re
    from datetime import date

    safe_q = re.sub(r'[^\w\u4e00-\u9fff\-_ ]', '', question[:40]).strip().replace(" ", "-")
    filename = f"{settings.vault.wiki_queries_dir}/{safe_q}-{date.today()}.md"
    content = f"# {question}\n\n{answer.replace('ARCHIVABLE: true', '').strip()}"
    write_wiki_note(filename, content, metadata={"title": question, "type": "query-result", "date": str(date.today())})
    _update_index(question, filename, f"查询结果：{question[:30]}...")
    console.print(f"\n[green]✓ 答案已归档：{filename}[/green]")


async def lint(*, stream: bool = True) -> str:
    """对 Wiki 进行健康检查。

    Args:
        stream: 是否流式输出。
    Returns:
        LLM 的完整检查报告。
    """
    wiki_context = _load_wiki_context(max_files=50)
    user_prompt = f"""请对以下 Wiki 进行全面健康检查：

    ---Wiki 内容---
    {wiki_context}
    """
    system, messages = llm.build_messages(_LINT_SYSTEM.format(wiki_path=settings.vault.wiki_path), [], user_prompt)

    if stream:
        console.print("\n[cyan]Nemsy 正在检查 Wiki 健康状态...[/cyan]\n")
        full_response = ""
        async for chunk in llm.chat_stream(system, messages):
            console.print(chunk, end="", markup=False)
            full_response += chunk
        console.print()
    else:
        full_response = await llm.chat(system, messages)

    append_log("lint", "Wiki 健康检查", detail="自动健检完成")
    return full_response


# ---------------------------------------------------------------------------
# 对话模式（chat loop 的单轮调用）
# ---------------------------------------------------------------------------

async def chat_turn(
    user_input: str,
    history: list[llm.Message],
    *,
    stream: bool = True,
) -> str:
    """普通对话模式的单轮调用，支持历史记忆。

    Args:
        user_input: 用户输入。
        history: 历史对话消息列表。
        stream: 是否流式输出。
    Returns:
        LLM 回复文本。
    """
    wiki_context = _load_wiki_context(max_files=20)
    system_prompt = _BASE_SYSTEM.format(wiki_path=settings.vault.wiki_path) + f"\n\n当前 Wiki 摘要：\n{wiki_context}"
    system, messages = llm.build_messages(system_prompt, history, user_input)

    if stream:
        full_response = ""
        async for chunk in llm.chat_stream(system, messages):
            console.print(chunk, end="", markup=False)
            full_response += chunk
        console.print()
        return full_response
    else:
        return await llm.chat(system, messages)
