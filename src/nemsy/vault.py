"""Obsidian Vault 读写操作模块。

职责：读取/写入/创建 Vault 中的 Markdown 文件，管理 Wiki 目录结构。
删除操作必须经过用户确认（click.confirm）。
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Iterator

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

def iter_notes(directory: Path | None = None) -> Iterator[Note]:
    """遍历目录下的所有 Markdown 笔记（递归），跳过忽略目录。

    Args:
        directory: 起始目录，默认为 Vault 根目录。
    """
    root = directory or settings.vault.path
    ignore = set(settings.vault.ignore_dirs)
    exts = set(settings.vault.include_extensions)

    for path in root.rglob("*"):
        if any(part in ignore for part in path.parts):
            continue
        if path.suffix in exts and path.is_file():
            yield Note(path)


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
        directory: 搜索范围，默认为整个 Vault。
    """
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    results: list[Note] = []
    for note in iter_notes(directory):
        try:
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
    append_wiki_note("log.md", entry)


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
