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
  [cyan]/ingest <路径> --wide[/cyan]          加载更多 Wiki 上下文（适合 Wiki 已积累大量内容时）
  [cyan]/ingest <路径> --dry-run[/cyan]      仅预览待摄取文件，不实际执行
  [cyan]/save[/cyan]                        将当前对话整理为洞见归档到 insights/
  [cyan]/save <主题>[/cyan]                  归档时附加主题提示，帮助 LLM 聚焦
  [cyan]/query <问题>[/cyan]                 向 Wiki 精确提问（严格基于 Wiki，不引入训练知识）
  [cyan]/query <问题> -a[/cyan]              同上，并将答案归档到 queries/
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

    from nemsy.agent import chat_turn, _load_wiki_context
    from nemsy.llm import Message

    history: list[Message] = []

    # 优化1：会话级缓存——整个 chat session 只加载一次 Wiki 上下文，
    # 保证每轮传入的字符串对象字节级一致，稳定触发 DeepSeek KV Cache 命中。
    console.print("[dim]正在加载 Wiki 上下文...[/dim]", end="\r")
    _session_wiki_context = _load_wiki_context(max_files=20)
    console.print(" " * 30, end="\r")  # 清除提示行

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
                # 解析内联 flag：-r / --recursive，-f / --force，--wide，--dry-run
                _recursive = False
                _force = False
                _dry_run = False
                _wide = False
                _tokens = arg.split()
                _path_tokens: list[str] = []
                for _tok in _tokens:
                    if _tok in ("-r", "--recursive"):
                        _recursive = True
                    elif _tok in ("-f", "--force"):
                        _force = True
                    elif _tok == "--dry-run":
                        _dry_run = True
                    elif _tok == "--wide":
                        _wide = True
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
                    wide=_wide,
                ))
                continue
            elif cmd == "query":
                if not arg:
                    console.print("[red]用法：/query <问题> [-a]  （-a 归档答案）[/red]")
                    continue
                # 解析 -a / --archive 标志
                _archive_flag = False
                if arg.endswith(" -a") or arg.endswith(" --archive"):
                    _archive_flag = True
                    arg = arg.replace(" -a", "").replace(" --archive", "").strip()
                # 复用会话缓存，避免重复读盘，保证 KV Cache 命中
                result = asyncio.run(_run_query(arg, archive=_archive_flag, wiki_context=_session_wiki_context, return_response=True))
                # 检查 ARCHIVABLE 提示（未归档时）
                if not _archive_flag and result and "ARCHIVABLE: true" in result:
                    console.print("\n[dim]💡 此回答可归档。使用 /query <问题> -a 可保存到 Wiki。[/dim]")
                continue
            elif cmd == "sources":
                _print_sources()
                continue
            elif cmd == "save":
                asyncio.run(_run_save(history, topic=arg or None))
                continue
            else:
                console.print(f"[red]未知命令：/{cmd}，输入 /help 查看可用命令[/red]")
                continue

        # 普通对话
        console.print("\n[bold cyan]Nemsy >[/bold cyan] ", end="")
        response = asyncio.run(chat_turn(user_input, history, stream=True, wiki_context=_session_wiki_context))

        # 更新历史
        history.append({"role": "user", "content": user_input})
        history.append({"role": "assistant", "content": response})

        # ARCHIVABLE: true 自动检测
        if "ARCHIVABLE: true" in response:
            console.print("\n[yellow]💡 Nemsy 认为此回答值得归档，是否保存到 insights/？[y/N][/yellow] ", end="")
            try:
                confirm = input().strip().lower()
            except (KeyboardInterrupt, EOFError):
                confirm = ""
            if confirm in ("y", "yes"):
                asyncio.run(_run_save(history, topic=None))

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
@click.option("--wide", is_flag=True, default=False, help="加载更多 Wiki 上下文（50 页 vs 默认 10 页），适合 Wiki 已积累大量内容时使用")
def ingest(path_arg: Path | None, title: str | None, recursive: bool, force: bool, dry_run: bool, wide: bool) -> None:
    """摄取文件或目录进 Wiki。

    PATH 可以是单个 Markdown 文件，也可以是目录。
    不传 PATH 时自动扫描全部 origin-sources/ 根目录。
    目录模式下默认只扫一层，加 --recursive 穿透子目录。
    已摄取过的文件会被自动跳过，加 --force 强制重新摄取。
    加 --wide 可在摄取时加载更多 Wiki 上下文页面，适合 Wiki 已积累大量内容时使用。
    """
    settings.ensure_dirs()
    asyncio.run(_run_ingest_batch(path_arg, title=title, recursive=recursive, force=force, dry_run=dry_run, wide=wide))


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

async def _run_ingest_single(
    path: Path,
    content: str | None = None,
    title: str | None = None,
    wide: bool = False,
    out_console: "Console | None" = None,
    stream: bool = True,
) -> bool:
    """摄取单个文件，返回是否成功。

    Args:
        path: 文件路径。
        content: 预读的文件内容，为 None 时自动读取。
        title: 资料标题，默认使用文件名。
        wide: 是否加载更多 Wiki 上下文。
        out_console: 输出使用的 Console 实例，批量模式下传 progress.console。
        stream: 是否流式输出 LLM token。
    """
    from nemsy.agent import ingest as agent_ingest
    from nemsy.vault import find_index_context

    _con = out_console or console
    if not path.exists():
        _con.print(f"[red]文件不存在：{_display_path(path)}[/red]")
        return False

    if content is None:
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            _con.print(f"[red]读取失败：{_display_path(path)} — {e}[/red]")
            return False

    # 读取目录语境（_index.md），无则为 None
    index_context = find_index_context(path)

    source_title = title or path.stem
    await agent_ingest(
        content,
        source_title,
        source_path=path,
        index_context=index_context,
        wide=wide,
        stream=stream,
        out_console=_con,
    )
    return True


def _display_path(path: Path) -> str:
    """将路径转为用户友好的显示格式。

    origin-sources 下的路径显示为相对路径（与命令行输入格式一致）。
    其他路径保持原样。
    """
    raw_root = settings.vault.raw_sources_path
    if raw_root:
        try:
            rel = path.relative_to(raw_root)
            return str(rel)
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
    wide: bool = False,
) -> None:
    """批量摄取文件或目录。

    Args:
        wide: 是否加载更多 Wiki 上下文（50 页 vs 默认 10 页）。
    """
    from nemsy.vault import collect_files, get_file_status

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

    # 读取内容并按状态分组
    pending: list[tuple[Path, str]] = []   # (path, content) 待摄取（new / changed）
    skipped: list[Path] = []               # done，已是最新
    empty: list[Path] = []                 # 空文件，记录但跳过 LLM

    for f in files:
        try:
            content = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            content = ""
        status = get_file_status(f, content)

        if status == "empty":
            empty.append(f)
            # 空文件也写入 log，标记 status=empty
            from nemsy.vault import record_ingest as _record
            _record(f, content)
        elif status == "done" and not force:
            skipped.append(f)
        else:
            # new / changed / force 覆盖
            pending.append((f, content))

    is_batch = path.is_dir() or len(files) > 1

    # 统计摘要
    if is_batch:
        console.print(f"[dim]路径：{_display_path(path)}[/dim]")
        parts = [
            f"共 [cyan]{len(files)}[/cyan] 个文件",
            f"[green]{len(pending)}[/green] 个待摄取",
        ]
        if skipped:
            parts.append(f"[dim]{len(skipped)} 个已跳过（done）[/dim]")
        if empty:
            parts.append(f"[dim]{len(empty)} 个空文件[/dim]")
        wide_badge = " [bold magenta]（--wide：宽上下文）[/bold magenta]" if wide else ""
        console.print(
            f"[bold cyan]批量摄取[/bold cyan] " + "，".join(parts)
            + (" [bold yellow]（--force 强制全量）[/bold yellow]" if force else "")
            + wide_badge
        )
        if skipped:
            console.print(f"[dim]已跳过（done）：{', '.join(f.name for f in skipped[:5])}"
                         f"{'...' if len(skipped) > 5 else ''}[/dim]")
        if empty:
            console.print(f"[dim]空文件（已记录）：{', '.join(f.name for f in empty[:5])}"
                         f"{'...' if len(empty) > 5 else ''}[/dim]")

    if dry_run:
        console.print("\n[yellow]--dry-run 模式，仅列出待摄取文件，不实际执行：[/yellow]")
        for f, _ in pending:
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
        f, content = pending[0]
        await _run_ingest_single(f, content=content, title=title, wide=wide)
        return

    # 批量模式：带进度条
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, MofNCompleteColumn, TimeElapsedColumn

    success = 0
    failed = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[cyan]{task.fields[current_file]}", justify="left"),
        BarColumn(bar_width=None),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
        refresh_per_second=4,  # 降低刷新率，减少闪烁
    ) as progress:
        task = progress.add_task("", total=len(pending), current_file="准备中...")
        for f, content in pending:
            short_name = _display_path(f)
            # 更新描述，不影响进度条刷新节奏
            progress.update(task, current_file=short_name)
            # 批量模式关闭流式输出，结果由进度条上方统一打印
            ok = await _run_ingest_single(
                f, content=content, wide=wide,
                out_console=progress.console,
                stream=False,
            )
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


async def _run_query(question: str, *, archive: bool = False, use_reason: bool = False, wiki_context: str | None = None, return_response: bool = False) -> str | None:
    """执行查询操作。
    
    Args:
        question: 用户问题。
        archive: 是否归档答案。
        use_reason: 是否使用深度推理模型。
        wiki_context: 预加载的 Wiki 上下文，为 None 时自动加载。
            chat 模式调用时传入会话缓存，避免重复读盘并保证 KV Cache 命中。
        return_response: 是否返回响应内容。chat 内联命令需要检查 ARCHIVABLE 时设为 True。
    Returns:
        return_response=True 时返回响应内容，否则返回 None。
    """
    from nemsy import llm as llm_module
    from nemsy.agent import query as agent_query, _load_wiki_context, _archive_query_result, append_log

    if use_reason:
        # 使用 reasoner 模式
        ctx = wiki_context if wiki_context is not None else _load_wiki_context()
        from nemsy.agent import _QUERY_SYSTEM
        user_prompt = f"问题：{question}\n\n---Wiki 内容---\n{ctx}"
        system, messages = llm_module.build_messages(
            _QUERY_SYSTEM.format(wiki_path=settings.vault.wiki_path), [], user_prompt
        )
        console.print(f"\n[cyan]Nemsy（深度推理）正在思考：{question}[/cyan]\n")
        response = await llm_module.reason(system, messages)
        console.print(response)
        if archive:
            _archive_query_result(question, response)
        elif "ARCHIVABLE: true" in response:
            console.print("\n[dim]💡 此回答可归档。添加 --archive 参数可保存到 Wiki。[/dim]")
        append_log("query", question, detail="使用 reasoner 模式")
        return response if return_response else None
    else:
        response = await agent_query(question, archive=archive, wiki_context=wiki_context)
        # 独立命令模式（非 chat 内联）时，如果未归档但有 ARCHIVABLE，给出提示
        if not return_response and not archive and "ARCHIVABLE: true" in response:
            console.print("\n[dim]💡 此回答可归档。添加 --archive 参数可保存到 Wiki。[/dim]")
        return response if return_response else None


async def _run_save(history: list, *, topic: str | None = None) -> None:
    """将对话历史整理为洞见归档到 insights/。"""
    from nemsy.agent import save_insight
    from nemsy.llm import Message

    if not history:
        console.print("[yellow]⚠ 当前对话历史为空，请先进行对话再归档。[/yellow]")
        return
    await save_insight(history, topic=topic)


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


def smoke():
    """运行烟雾测试（快速验证核心功能）。"""
    import subprocess

    console.print("\n[cyan]正在运行 Nemsy 烟雾测试...[/cyan]\n")
    console.print("[dim]测试会调用真实 LLM API，生成的内容需手动清理。[/dim]\n")

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_smoke.py", "-v", "-s"],
        cwd=Path(__file__).parent.parent.parent,  # 项目根目录
    )

    if result.returncode == 0:
        console.print("\n[green]✓ 烟雾测试通过！[/green]")
    else:
        console.print("\n[red]✗ 烟雾测试失败，请检查输出。[/red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
