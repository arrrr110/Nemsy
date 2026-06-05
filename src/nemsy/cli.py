"""Nemsy CLI 入口模块。

命令：
  nemsy chat           — 进入持续对话模式
  nemsy ingest <file>  — 摄取一个本地 Markdown 文件
  nemsy query <问题>   — 单次提问
  nemsy lint           — Wiki 健康检查
  nemsy status         — 显示 Wiki 和 Vault 状态
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from nemsy import __version__
from nemsy.config import settings

console = Console()

# ---------------------------------------------------------------------------
# 欢迎语
# ---------------------------------------------------------------------------

WELCOME = """\
[bold cyan]Nemsy[/bold cyan] [dim]v{version}[/dim]
[dim]你好！我是 Nemsy，你的个人知识助手。[/dim]
[dim]Wiki 目录：{wiki_path}[/dim]
[dim]输入 /help 查看可用命令，输入 /quit 退出。[/dim]
"""

CHAT_HELP = """\
[bold]对话内命令：[/bold]
  [cyan]/ingest <文件路径>[/cyan]  摄取本地文件进 Wiki
  [cyan]/query <问题>[/cyan]       向 Wiki 提问（同当前输入）
  [cyan]/lint[/cyan]               运行 Wiki 健康检查
  [cyan]/status[/cyan]             显示 Wiki 状态
  [cyan]/help[/cyan]               显示此帮助
  [cyan]/quit[/cyan] 或 [cyan]/exit[/cyan]      退出
"""


# ---------------------------------------------------------------------------
# CLI 根命令
# ---------------------------------------------------------------------------

@click.group(invoke_without_command=True)
@click.version_option(__version__, prog_name="Nemsy")
@click.pass_context
def main(ctx: click.Context) -> None:
    """Nemsy — 由 DeepSeek 驱动的个人知识助手。"""
    if ctx.invoked_subcommand is None:
        # 默认进入 chat 模式
        ctx.invoke(chat)


# ---------------------------------------------------------------------------
# chat 命令
# ---------------------------------------------------------------------------

@main.command()
def chat() -> None:
    """进入持续对话模式（默认命令）。"""
    settings.ensure_dirs()

    if settings.cli.show_welcome:
        console.print(
            Panel(
                WELCOME.format(version=__version__, wiki_path=settings.vault.wiki_path),
                border_style="cyan",
                expand=False,
            )
        )

    if not settings.llm.api_key:
        console.print("[red]⚠ 未检测到 DEEPSEEK_API_KEY，请在 .env 文件中配置后重启。[/red]")
        sys.exit(1)

    from nemsy.agent import chat_turn
    from nemsy.llm import Message

    history: list[Message] = []

    while True:
        try:
            user_input = console.input("[bold cyan]你 >[/bold cyan] ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\n[dim]再见！[/dim]")
            break

        if not user_input:
            continue

        # 内联命令处理
        if user_input.startswith("/"):
            parts = user_input[1:].split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""

            if cmd in ("quit", "exit", "q"):
                console.print("[dim]再见！[/dim]")
                break
            elif cmd == "help":
                console.print(CHAT_HELP)
                continue
            elif cmd == "status":
                _print_status()
                continue
            elif cmd == "lint":
                asyncio.run(_run_lint())
                continue
            elif cmd == "ingest":
                if not arg:
                    console.print("[red]用法：/ingest <文件路径>[/red]")
                    continue
                asyncio.run(_run_ingest(arg))
                continue
            elif cmd == "query":
                if not arg:
                    console.print("[red]用法：/query <问题>[/red]")
                    continue
                asyncio.run(_run_query(arg))
                continue
            else:
                console.print(f"[red]未知命令：/{cmd}，输入 /help 查看可用命令[/red]")
                continue

        # 普通对话
        console.print("\n[bold cyan]Nemsy >[/bold cyan] ", end="")
        response = asyncio.run(chat_turn(user_input, history, stream=True))

        # 更新历史
        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": response})

        # 如果配置了最大轮数，裁剪历史
        max_turns = settings.memory.max_turns
        if max_turns > 0 and len(history) > max_turns * 2:
            history = history[-(max_turns * 2):]


# ---------------------------------------------------------------------------
# ingest 命令
# ---------------------------------------------------------------------------

@main.command()
@click.argument("file_path", type=click.Path(path_type=Path))
@click.option("--title", "-t", default=None, help="资料标题，默认使用文件名")
def ingest(file_path: Path, title: str | None) -> None:
    """摄取一个本地 Markdown 文件进 Wiki。"""
    settings.ensure_dirs()
    asyncio.run(_run_ingest(str(file_path), title=title))


# ---------------------------------------------------------------------------
# query 命令
# ---------------------------------------------------------------------------

@main.command()
@click.argument("question")
@click.option("--archive", "-a", is_flag=True, default=False, help="将答案归档为 Wiki 页面")
@click.option("--reason", "-r", is_flag=True, default=False, help="使用 deepseek-reasoner 深度推理")
def query(question: str, archive: bool, reason: bool) -> None:
    """向 Wiki 提出一个问题并获得综合答案。"""
    settings.ensure_dirs()
    asyncio.run(_run_query(question, archive=archive, use_reason=reason))


# ---------------------------------------------------------------------------
# lint 命令
# ---------------------------------------------------------------------------

@main.command()
def lint() -> None:
    """对 Wiki 进行健康检查，发现矛盾、孤立页面、缺失链接等问题。"""
    settings.ensure_dirs()
    asyncio.run(_run_lint())


# ---------------------------------------------------------------------------
# status 命令
# ---------------------------------------------------------------------------

@main.command()
def status() -> None:
    """显示 Wiki 和 Vault 的当前状态。"""
    _print_status()


# ---------------------------------------------------------------------------
# 内部异步运行函数
# ---------------------------------------------------------------------------

async def _run_ingest(file_path_str: str, title: str | None = None) -> None:
    """执行摄取操作。"""
    from nemsy.agent import ingest as agent_ingest

    path = Path(file_path_str)
    if not path.exists():
        console.print(f"[red]文件不存在：{file_path_str}[/red]")
        return

    content = path.read_text(encoding="utf-8")
    source_title = title or path.stem
    await agent_ingest(content, source_title)


async def _run_query(question: str, *, archive: bool = False, use_reason: bool = False) -> None:
    """执行查询操作。"""
    from nemsy import llm as llm_module
    from nemsy.agent import query as agent_query, _load_wiki_context, _archive_query_result, append_log

    if use_reason:
        # 使用 reasoner 模式
        wiki_context = _load_wiki_context()
        from nemsy.agent import _QUERY_SYSTEM
        user_prompt = f"问题：{question}\n\n---Wiki 内容---\n{wiki_context}"
        messages = llm_module.build_messages(
            _QUERY_SYSTEM.format(wiki_path=settings.vault.wiki_path), [], user_prompt
        )
        console.print(f"\n[cyan]Nemsy（深度推理）正在思考：{question}[/cyan]\n")
        response = await llm_module.reason(messages)
        console.print(response)
        if archive:
            _archive_query_result(question, response)
        append_log("query", question, detail="使用 reasoner 模式")
    else:
        await agent_query(question, archive=archive)


async def _run_lint() -> None:
    """执行 Wiki 健康检查。"""
    from nemsy.agent import lint as agent_lint
    await agent_lint()


# ---------------------------------------------------------------------------
# 状态显示
# ---------------------------------------------------------------------------

def _print_status() -> None:
    """打印 Wiki 和 Vault 的状态信息。"""
    from nemsy.vault import list_wiki_notes

    vault_path = settings.vault.path
    wiki_path = settings.vault.wiki_path
    raw_dir = settings.vault.raw_sources_path
    wiki_notes = list_wiki_notes()

    # 统计 Wiki 子目录分布
    sources_count = len(list(wiki_path.glob("sources/*.md"))) if wiki_path.exists() else 0
    queries_count = len(list(wiki_path.glob("queries/*.md"))) if wiki_path.exists() else 0
    entities_count = len(list(wiki_path.glob("entities/*.md"))) if wiki_path.exists() else 0
    concepts_count = len(list(wiki_path.glob("concepts/*.md"))) if wiki_path.exists() else 0

    # Vault 信息
    vault_table = Table(title="Vault", border_style="cyan", show_header=False, box=None)
    vault_table.add_column("项目", style="bold dim", width=16)
    vault_table.add_column("值")
    vault_table.add_row("路径", str(vault_path))
    vault_table.add_row("状态", "[green]✓ 已找到[/green]" if vault_path.exists() else "[red]✗ 未找到[/red]")
    vault_table.add_row(
        "原始资料目录",
        f"[green]✓[/green] {raw_dir}" if raw_dir and raw_dir.exists() else (
            f"[yellow]⚠ 路径不存在：{raw_dir}[/yellow]" if raw_dir else
            "[dim]未配置 — 在 config/settings.toml 的 raw_sources_dir 填入[/dim]"
        ),
    )

    # Wiki 信息
    wiki_table = Table(title="Wiki", border_style="cyan", show_header=False, box=None)
    wiki_table.add_column("项目", style="bold dim", width=16)
    wiki_table.add_column("值")
    wiki_table.add_row("目录", str(wiki_path))
    wiki_table.add_row("状态", "[green]✓ 已找到[/green]" if wiki_path.exists() else "[yellow]⚠ 尚未创建[/yellow]")
    wiki_table.add_row("页面总数", str(len(wiki_notes)))
    wiki_table.add_row(
        "分布",
        f"sources {sources_count}  queries {queries_count}  entities {entities_count}  concepts {concepts_count}",
    )
    has_index = (wiki_path / "index.md").exists() if wiki_path.exists() else False
    has_log = (wiki_path / "log.md").exists() if wiki_path.exists() else False
    wiki_table.add_row(
        "特殊文件",
        f"index {'[green]✓[/green]' if has_index else '[dim]✗[/dim]'}  "
        f"log {'[green]✓[/green]' if has_log else '[dim]✗[/dim]'}",
    )

    # LLM 信息
    llm_table = Table(title="LLM", border_style="cyan", show_header=False, box=None)
    llm_table.add_column("项目", style="bold dim", width=16)
    llm_table.add_column("值")
    llm_table.add_row("API Key", "[green]✓ 已配置[/green]" if settings.llm.api_key else "[red]✗ 未配置[/red]")
    llm_table.add_row("Base URL", settings.llm.base_url)
    llm_table.add_row("默认模型", settings.llm.default_model)
    llm_table.add_row("推理模型", settings.llm.reasoning_model)

    console.print()
    console.print(vault_table)
    console.print()
    console.print(wiki_table)
    console.print()
    console.print(llm_table)
    console.print()


if __name__ == "__main__":
    main()
