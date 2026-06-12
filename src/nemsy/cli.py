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
  [cyan]/ingest <路径>[/cyan]                摄取文件或目录进 Wiki
  [cyan]/ingest <路径> -r[/cyan]             穿透子目录递归摄取
  [cyan]/ingest <路径> -f[/cyan]             强制重新摄取（忽略历史记录）
  [cyan]/ingest <路径> --dry-run[/cyan]      仅预览待摄取文件，不实际执行
  [cyan]/query <问题>[/cyan]                 向 Wiki 提问
  [cyan]/sources[/cyan]                     列出原始资料层的所有文件
  [cyan]/lint[/cyan]                        运行 Wiki 健康检查
  [cyan]/status[/cyan]                     显示 Wiki 状态
  [cyan]/help[/cyan]                        显示此帮助
  [cyan]/quit[/cyan] 或 [cyan]/exit[/cyan]             退出
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
                # 解析内联 flag：-r / --recursive，-f / --force，--dry-run
                _recursive = False
                _force = False
                _dry_run = False
                _tokens = arg.split()
                _path_tokens: list[str] = []
                for _tok in _tokens:
                    if _tok in ("-r", "--recursive"):
                        _recursive = True
                    elif _tok in ("-f", "--force"):
                        _force = True
                    elif _tok == "--dry-run":
                        _dry_run = True
                    else:
                        _path_tokens.append(_tok)
                _ingest_path = " ".join(_path_tokens)
                # 路径为空时传 None，触发全量扫描逻辑
                _resolved_path = Path(_ingest_path) if _ingest_path else None
                asyncio.run(_run_ingest_batch(
                    _resolved_path,
                    recursive=_recursive,
                    force=_force,
                    dry_run=_dry_run,
                ))
                continue
            elif cmd == "query":
                if not arg:
                    console.print("[red]用法：/query <问题>[/red]")
                    continue
                asyncio.run(_run_query(arg))
                continue
            elif cmd == "sources":
                _print_sources()
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
@click.argument("path_arg", metavar="PATH", type=click.Path(path_type=Path), required=False, default=None)
@click.option("--title", "-t", default=None, help="资料标题（仅单文件模式有效），默认使用文件名")
@click.option("--recursive", "-r", is_flag=True, default=False, help="穿透子目录递归摄取（目录模式）")
@click.option("--force", "-f", is_flag=True, default=False, help="强制重新摄取，忽略已摄取记录")
@click.option("--dry-run", is_flag=True, default=False, help="仅列出待摄取文件，不实际执行")
def ingest(path_arg: Path | None, title: str | None, recursive: bool, force: bool, dry_run: bool) -> None:
    """摄取文件或目录进 Wiki。

    PATH 可以是单个 Markdown 文件，也可以是目录。
    不传 PATH 时自动扫描全部 origin-sources/ 根目录。
    目录模式下默认只扫一层，加 --recursive 穿透子目录。
    已摄取过的文件会被自动跳过，加 --force 强制重新摄取。
    """
    settings.ensure_dirs()
    asyncio.run(_run_ingest_batch(path_arg, title=title, recursive=recursive, force=force, dry_run=dry_run))


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

async def _run_ingest_single(path: Path, title: str | None = None) -> bool:
    """摄取单个文件，返回是否成功。"""
    from nemsy.agent import ingest as agent_ingest
    from nemsy.vault import record_ingest

    if not path.exists():
        console.print(f"[red]文件不存在：{_display_path(path)}[/red]")
        return False

    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        console.print(f"[red]读取失败：{_display_path(path)} — {e}[/red]")
        return False

    source_title = title or path.stem
    await agent_ingest(content, source_title)
    record_ingest(path)
    return True


def _display_path(path: Path) -> str:
    """将路径转为用户友好的显示格式。

    origin-sources 下的路径显示为 @子路径（例如 @个人认知/感悟/xxx.md）。
    其他路径保持原样。
    """
    raw_root = settings.vault.raw_sources_path
    if raw_root:
        try:
            rel = path.relative_to(raw_root)
            return f"@{rel}"
        except ValueError:
            pass
    return str(path)


def _resolve_ingest_path(path: Path) -> Path:
    """将摄取路径解析为绝对路径。

    解析规则（优先级从高到低）：
    1. 已经是绝对路径 → 直接使用
    2. 是相对路径 → 尝试以 raw_sources_path 为根解析
    3. raw_sources_path 未配置或拼合后不存在 → 回退到当前工作目录
    """
    if path.is_absolute():
        return path

    raw_root = settings.vault.raw_sources_path
    if raw_root:
        candidate = raw_root / path
        if candidate.exists():
            return candidate

    # 回退：相对于当前工作目录
    return Path.cwd() / path


async def _run_ingest_batch(
    path: Path | None,
    *,
    title: str | None = None,
    recursive: bool = False,
    force: bool = False,
    dry_run: bool = False,
) -> None:
    """批量摄取文件或目录。"""
    from nemsy.vault import collect_files, is_ingested

    # PATH 未传时，默认扫描 origin-sources/ 根目录
    if path is None:
        raw_root = settings.vault.raw_sources_path
        if not raw_root:
            console.print("[red]⚠ 未配置 origin-sources 目录，请在 config/settings.toml 的 raw_sources_dir 填入。[/red]")
            return
        path = raw_root
    else:
        path = _resolve_ingest_path(path)

    files = collect_files(path, recursive=recursive)

    if not files:
        if path.is_file():
            console.print(f"[yellow]⚠ 不支持的文件类型：{_display_path(path)}（仅支持 .md / .txt）[/yellow]")
        else:
            console.print(f"[yellow]⚠ 未在以下路径找到任何可摄取文件：{_display_path(path)}[/yellow]")
        return

    # 过滤已摄取文件（除非 --force）
    pending: list[Path] = []
    skipped: list[Path] = []
    for f in files:
        if not force and is_ingested(f):
            skipped.append(f)
        else:
            pending.append(f)

    # 统计摘要
    is_batch = path.is_dir() or len(files) > 1
    if is_batch:
        console.print(f"[dim]路径：{_display_path(path)}[/dim]")
        console.print(
            f"[bold cyan]批量摄取[/bold cyan] "
            f"共 [cyan]{len(files)}[/cyan] 个文件，"
            f"[green]{len(pending)}[/green] 个待摄取，"
            f"[dim]{len(skipped)}[/dim] 个已跳过"
            + ("[bold yellow]（--force 强制全量）[/bold yellow]" if force else "")
        )
        if skipped:
            console.print(f"[dim]已跳过（已摄取）：{', '.join(f.name for f in skipped[:5])}"
                         f"{'...' if len(skipped) > 5 else ''}[/dim]")

    if dry_run:
        console.print("\n[yellow]--dry-run 模式，仅列出待摄取文件，不实际执行：[/yellow]")
        for f in pending:
            console.print(f"  [dim]{_display_path(f)}[/dim]")
        if not pending:
            console.print("  [dim]（无待处理文件）[/dim]")
        return

    # 无路径模式（全量扫描）时，文件较多需确认
    if path == settings.vault.raw_sources_path and len(pending) > 20:
        console.print(
            f"[yellow]No path specified, scanning all of origin-sources/ "
            f"({len(pending)} files). Continue? [y/N][/yellow]",
            end=" ",
        )
        try:
            confirm = input().strip().lower()
        except (KeyboardInterrupt, EOFError):
            confirm = ""
        if confirm not in ("y", "yes"):
            console.print("[dim]已取消。[/dim]")
            return

    if not pending:
        console.print("[green]✓ 所有文件已摄取过，无需重复处理。加 --force 强制重新摄取。[/green]")
        return

    # 单文件模式直接摄取（允许传 --title）
    if not is_batch:
        await _run_ingest_single(pending[0], title=title)
        return

    # 批量模式：带进度条
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn

    success = 0
    failed = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("[cyan]摄取中...", total=len(pending))
        for f in pending:
            progress.update(task, description=f"[cyan]{_display_path(f)[:50]}")
            ok = await _run_ingest_single(f)
            if ok:
                success += 1
            else:
                failed += 1
            progress.advance(task)

    console.print(
        f"\n[bold]批量摄取完成[/bold]：[green]{success} 成功[/green]"
        + (f"，[red]{failed} 失败[/red]" if failed else "")
    )


# 保留旧接口供 chat 内联命令调用
async def _run_ingest(file_path_str: str, title: str | None = None) -> None:
    """执行摄取操作（旧接口，兼容 chat 内联 /ingest 命令）。"""
    await _run_ingest_batch(Path(file_path_str), title=title, force=False)


async def _run_query(question: str, *, archive: bool = False, use_reason: bool = False) -> None:
    """执行查询操作。"""
    from nemsy import llm as llm_module
    from nemsy.agent import query as agent_query, _load_wiki_context, _archive_query_result, append_log

    if use_reason:
        # 使用 reasoner 模式
        wiki_context = _load_wiki_context()
        from nemsy.agent import _QUERY_SYSTEM
        user_prompt = f"问题：{question}\n\n---Wiki 内容---\n{wiki_context}"
        system, messages = llm_module.build_messages(
            _QUERY_SYSTEM.format(wiki_path=settings.vault.wiki_path), [], user_prompt
        )
        console.print(f"\n[cyan]Nemsy（深度推理）正在思考：{question}[/cyan]\n")
        response = await llm_module.reason(system, messages)
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

def _print_sources() -> None:
    """列出原始资料层（origin-sources）中的所有文件。"""
    from rich.tree import Tree
    from nemsy.vault import collect_files

    raw_path = settings.vault.raw_sources_path
    if not raw_path:
        console.print("[yellow]⚠ 原始资料目录未配置，请在 config/settings.toml 的 raw_sources_dir 填入。[/yellow]")
        return
    if not raw_path.exists():
        console.print(f"[yellow]⚠ 原始资料目录不存在：{raw_path}[/yellow]")
        return

    paths = collect_files(raw_path, recursive=True)
    if not paths:
        console.print(f"[dim]原始资料目录为空：{raw_path}[/dim]")
        return

    tree = Tree(f"[bold cyan]{raw_path.name}/[/bold cyan]  [dim]({len(paths)} 个文件)[/dim]")
    added_branches: dict[str, object] = {}
    for p in paths:
        rel = p.relative_to(raw_path)
        parent = str(rel.parent) if str(rel.parent) != "." else ""
        if parent:
            if parent not in added_branches:
                added_branches[parent] = tree.add(f"[cyan]{parent}/[/cyan]")
            branch = added_branches[parent]
        else:
            branch = tree
        branch.add(f"[white]{rel.name}[/white]")  # type: ignore[union-attr]

    console.print(tree)


def _print_status() -> None:
    """打印 Wiki 和 Vault 的状态信息。"""
    from nemsy.vault import list_wiki_notes

    vault_path = settings.vault.path
    wiki_path = settings.vault.wiki_path
    raw_dir = settings.vault.raw_sources_path
    wiki_notes = list_wiki_notes()

    # 统计 Wiki 子目录分布
    v = settings.vault
    sources_count = len(list(wiki_path.glob(f"{v.wiki_sources_dir}/*.md"))) if wiki_path.exists() else 0
    queries_count = len(list(wiki_path.glob(f"{v.wiki_queries_dir}/*.md"))) if wiki_path.exists() else 0

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
        f"sources {sources_count}  queries {queries_count}",
    )
    has_index = (wiki_path / v.wiki_index_file).exists() if wiki_path.exists() else False
    has_log = (wiki_path / v.wiki_log_file).exists() if wiki_path.exists() else False
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
