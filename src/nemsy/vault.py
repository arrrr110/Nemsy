"""Obsidian Vault 读写操作模块。

职责：读取/写入/创建 Vault 中的 Markdown 文件，管理 Wiki 目录结构。
删除操作必须经过用户确认（click.confirm）。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import frontmatter

from nemsy.config import settings


# ---------------------------------------------------------------------------
# 数据类型
# ---------------------------------------------------------------------------

class Note:
    """代表一个 Obsidian 笔记文件。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._post: frontmatter.Post | None = None

    @property
    def relative_path(self) -> Path:
        """相对于 Vault 根目录的路径。"""
        return self.path.relative_to(settings.vault.path)

    @property
    def title(self) -> str:
        """笔记标题，优先取 frontmatter 中的 title，否则用文件名。"""
        post = self._load()
        return str(post.get("title", self.path.stem))

    @property
    def content(self) -> str:
        """笔记正文（不含 frontmatter）。"""
        return self._load().content

    @property
    def metadata(self) -> dict:
        """Frontmatter 元数据。"""
        return dict(self._load().metadata)

    @property
    def full_text(self) -> str:
        """原始文件全文（含 frontmatter）。"""
        return self.path.read_text(encoding="utf-8")

    def _load(self) -> frontmatter.Post:
        if self._post is None:
            self._post = frontmatter.load(str(self.path))
        return self._post

    def __repr__(self) -> str:
        return f"<Note {self.relative_path}>"


# ---------------------------------------------------------------------------
# Vault 读操作
# ---------------------------------------------------------------------------

def read_note(path: Path) -> Note:
    """读取单个笔记。

    Args:
        path: 笔记的绝对路径或相对于 Vault 根目录的路径。
    """
    if not path.is_absolute():
        path = settings.vault.path / path
    if not path.exists():
        raise FileNotFoundError(f"笔记不存在：{path}")
    return Note(path)


def search_notes(query: str, directory: Path | None = None) -> list[Note]:
    """在笔记内容中全文搜索关键词（大小写不敏感）。

    Args:
        query: 搜索关键词。
        directory: 搜索范围，默认为 raw_sources_path，未配置则报错。
    """
    root = directory or settings.vault.raw_sources_path
    if root is None:
        raise ValueError("search_notes() 需要传入 directory 或在 settings.toml 中配置 raw_sources_dir")
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    results: list[Note] = []
    for path in collect_files(root, recursive=True):
        try:
            note = Note(path)
            if pattern.search(note.full_text):
                results.append(note)
        except Exception:
            continue
    return results


# ---------------------------------------------------------------------------
# Wiki 写操作
# ---------------------------------------------------------------------------

def _wiki_path(filename: str) -> Path:
    """将相对文件名解析为 Wiki 目录下的绝对路径。"""
    wiki = settings.vault.wiki_path
    wiki.mkdir(parents=True, exist_ok=True)
    return wiki / filename


def write_wiki_note(
    filename: str,
    content: str,
    metadata: dict | None = None,
) -> Path:
    """在 Wiki 目录中写入（或覆盖）一个笔记。

    Args:
        filename: 文件名（含 .md 扩展名），支持子目录如 "entities/Alice.md"。
        content: 笔记正文 Markdown 内容。
        metadata: 可选的 frontmatter 元数据字典。
    Returns:
        写入文件的绝对路径。
    """
    path = _wiki_path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)

    post = frontmatter.Post(content, **(metadata or {}))
    path.write_text(frontmatter.dumps(post), encoding="utf-8")
    return path


def append_wiki_note(filename: str, text: str) -> Path:
    """向 Wiki 笔记末尾追加内容（不覆盖原有内容）。

    Args:
        filename: 笔记文件名。
        text: 要追加的文本。
    Returns:
        文件的绝对路径。
    """
    path = _wiki_path(filename)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    separator = "\n" if existing and not existing.endswith("\n") else ""
    path.write_text(existing + separator + text, encoding="utf-8")
    return path


def read_wiki_note(filename: str) -> str | None:
    """读取 Wiki 笔记内容，不存在则返回 None。

    Args:
        filename: 笔记文件名。
    """
    path = _wiki_path(filename)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def wiki_note_exists(filename: str) -> bool:
    """检查 Wiki 笔记是否已存在。"""
    return _wiki_path(filename).exists()


def list_wiki_notes() -> list[Path]:
    """列出 Wiki 目录下所有 Markdown 笔记（递归）。"""
    wiki = settings.vault.wiki_path
    if not wiki.exists():
        return []
    return sorted(wiki.rglob("*.md"))


# ---------------------------------------------------------------------------
# 日志操作（log.md）
# ---------------------------------------------------------------------------

def append_log(operation: str, title: str, detail: str = "") -> None:
    """向 Wiki 的 log.md 追加一条操作记录。

    Args:
        operation: 操作类型，如 "ingest"、"query"、"lint"。
        title: 条目标题。
        detail: 可选的详细说明。
    """
    date_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    entry = f"\n## [{date_str}] {operation} | {title}\n"
    if detail:
        entry += f"\n{detail}\n"
    append_wiki_note(settings.vault.wiki_log_file, entry)


# ---------------------------------------------------------------------------
# 删除操作（必须询问用户）
# ---------------------------------------------------------------------------

def delete_wiki_note(filename: str, *, confirmed: bool = False) -> bool:
    """删除 Wiki 笔记。

    Args:
        filename: 笔记文件名。
        confirmed: 是否已经过用户确认。外部调用方负责调用 click.confirm()。
    Returns:
        True 表示已删除，False 表示用户取消或文件不存在。
    """
    path = _wiki_path(filename)
    if not path.exists():
        return False
    if not confirmed:
        raise RuntimeError("删除操作必须先通过 click.confirm() 获得用户确认，再传入 confirmed=True")
    path.unlink()
    return True


# ---------------------------------------------------------------------------
# 摄取日志（状态机，v2 格式）
# ---------------------------------------------------------------------------

# 空文件的固定 SHA-256（echo -n "" | sha256sum）
_EMPTY_HASH = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def _ingest_log_path() -> Path:
    """返回摄取日志文件路径（.nemsy/ingest_log.json）。"""
    log_path = Path(settings.memory.history_dir).parent / "ingest_log.json"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    return log_path


def compute_hash(content: str) -> str:
    """计算字符串内容的 SHA-256 哈希值（十六进制）。"""
    import hashlib
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _save_ingest_log(log: dict) -> None:
    """将 ingest_log 写回磁盘。"""
    _ingest_log_path().write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")


def load_ingest_log() -> dict:
    """加载摄取日志，返回 v2 格式结构。

    Returns:
        {"version": 2, "files": {路径: {...}}}
    """
    path = _ingest_log_path()
    if not path.exists():
        return {"version": 2, "files": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"version": 2, "files": {}}
    # 若已是 v2 格式直接返回
    if isinstance(data, dict) and data.get("version") == 2:
        return data
    # 否则返回空 v2（用户已声明不在乎旧数据）
    return {"version": 2, "files": {}}


def get_file_status(file_path: Path, content: str) -> str:
    """根据文件内容和 ingest_log 返回文件当前状态。

    Returns:
        "empty"   — 内容为空，跳过 LLM
        "done"    — 已摄取且 hash 未变，无需重新处理
        "changed" — 已摄取但 hash 有变化，需要重新摄取
        "new"     — 从未摄取过
    """
    stripped = content.strip()
    if not stripped:
        return "empty"

    current_hash = compute_hash(stripped)
    log = load_ingest_log()
    record = log["files"].get(str(file_path.resolve()))

    if record is None:
        return "new"
    if record.get("hash") == current_hash:
        return "done"
    return "changed"


def record_ingest(
    file_path: Path,
    content: str,
    *,
    ingest_mode: str | None = None,
    wiki_page: str | None = None,
) -> None:
    """将文件摄取结果写入 ingest_log（v2 格式）。

    Args:
        file_path: 被摄取文件的绝对路径。
        content: 文件内容（用于计算 hash）。
        ingest_mode: 摄取模式，"quick" 或 "full"。
        wiki_page: 生成的 Wiki 摘要页相对路径，如 "sources/xxx-2026-06-12.md"。
    """
    stripped = content.strip()
    current_hash = compute_hash(stripped) if stripped else _EMPTY_HASH
    status = "empty" if not stripped else "done"

    log = load_ingest_log()
    key = str(file_path.resolve())
    existing = log["files"].get(key, {})

    log["files"][key] = {
        "hash": current_hash,
        "prev_hash": existing.get("hash"),  # 记录上一次的 hash
        "size": len(content.encode("utf-8")),
        "status": status,
        "ingest_mode": ingest_mode,
        "ingested_at": existing.get("ingested_at", []) + [datetime.now().isoformat()],
        "wiki_page": wiki_page or existing.get("wiki_page"),
    }
    _save_ingest_log(log)


def is_ingested(file_path: Path) -> bool:
    """检查文件是否已经被摄取过（兼容旧调用，内部用 get_file_status 替代）。

    Returns:
        True 表示 log 中存在该文件记录。
    """
    log = load_ingest_log()
    return str(file_path.resolve()) in log["files"]


# 系统级黑名单：无论任何场景都跳过（不可配置）
# nemsy-wiki 通过 settings.vault.wiki_dir 动态注入，避免硬编码
_SYSTEM_IGNORE_DIRS = frozenset({
    ".venv", "venv", ".env", "node_modules", ".git", ".obsidian",
    ".trash", "__pycache__", ".DS_Store",
})


def collect_files(
    path: Path,
    *,
    recursive: bool = False,
    extensions: list[str] | None = None,
    ignore_dirs: frozenset[str] | None = None,
) -> list[Path]:
    """从文件或目录收集待摄取的文件列表。

    黑名单优先级（合并后生效）：
      系统级（_SYSTEM_IGNORE_DIRS） + 用户级（settings.vault.raw_sources_ignore） + ignore_dirs 参数

    Args:
        path: 文件或目录路径。
        recursive: 目录模式下是否递归穿透子目录。
        extensions: 限定扩展名列表，默认 ['.md', '.txt']。
        ignore_dirs: 额外要跳过的目录名集合（调用方传入，叠加到黑名单上）。
    Returns:
        按路径排序的文件列表（不含目录）。
    """
    if extensions is None:
        extensions = [".md", ".txt"]
    ext_set = set(extensions)

    # 合并三层黑名单：系统级 + wiki_dir（动态）+ 用户配置 + 调用方传入
    skip_dirs = _SYSTEM_IGNORE_DIRS | {settings.vault.wiki_dir} | set(settings.vault.raw_sources_ignore)
    if ignore_dirs:
        skip_dirs = skip_dirs | ignore_dirs

    if path.is_file():
        return [path] if path.suffix in ext_set else []

    if not path.is_dir():
        return []

    glob_fn = path.rglob if recursive else path.glob
    files: list[Path] = []
    for p in glob_fn("*"):
        # 跳过黑名单目录（检查路径中每一段）
        if any(part in skip_dirs for part in p.parts):
            continue
        if p.is_file() and p.suffix in ext_set:
            files.append(p)
    return sorted(files)
