"""Nemsy 烟雾测试 - 快速验证核心功能是否工作。

测试会调用真实 LLM API，测试完成后生成的 Wiki 内容需手动清理。
测试范围：ingest 和 query 的基本流程。
"""

import tempfile
from datetime import date
from pathlib import Path

import frontmatter
import pytest

from nemsy import agent
from nemsy.config import settings
from nemsy.vault import read_wiki_note, write_wiki_note


@pytest.fixture
def temp_test_file():
    """创建临时测试文件。"""
    content = """# 测试文章：AI 时代的知识管理

## 核心观点

在 AI 时代，个人知识管理的关键不在于存储更多信息，而在于建立知识之间的关联。
LLM 可以作为知识库的维护者，帮助我们发现隐藏的联系。

## 实践方法

1. 保持原始资料的完整性
2. 让 AI 提炼关键信息
3. 建立双向链接网络

## 参考来源

- Andrej Karpathy 的 LLM-Wiki 理念
- Obsidian 知识图谱实践
"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, encoding="utf-8"
    ) as f:
        f.write(content)
        path = Path(f.name)

    yield path

    # 测试完成后删除临时文件
    if path.exists():
        path.unlink()


@pytest.mark.asyncio
async def test_ingest_basic(temp_test_file):
    """测试基本的 ingest 功能。"""
    # 执行摄取
    result = await agent.ingest(
        source_content=temp_test_file.read_text(encoding="utf-8"),
        source_title=f"测试摄取-{date.today()}",
        source_path=temp_test_file,
        stream=False,  # 不流式输出，避免测试时打印过多内容
    )

    # 验证返回了 Wiki 页面路径
    assert result is not None
    assert result.endswith(".md")
    assert "sources/" in result

    # 验证生成的 Wiki 页面存在且包含必要字段
    wiki_path = settings.vault.wiki_path / result
    assert wiki_path.exists()

    note_text = read_wiki_note(result)
    assert note_text is not None
    note = frontmatter.loads(note_text)
    
    # 验证 frontmatter
    assert "title" in note.metadata
    assert "type" in note.metadata
    assert note.metadata["type"] == "source"
    assert "date" in note.metadata
    assert "tags" in note.metadata

    # 验证正文不为空
    assert len(note.content.strip()) > 50

    print(f"\n✓ Ingest 测试通过，生成页面：{result}")
    print(f"  Title: {note.metadata['title']}")
    print(f"  Tags: {note.metadata.get('tags', [])}")


@pytest.mark.asyncio
async def test_query_basic():
    """测试基本的 query 功能。"""
    # 先写入一个测试页面，确保 Wiki 有内容
    test_content = f"""# 测试知识页面

这是一个用于测试 query 功能的页面。

## 关键信息

- Nemsy 是一个 LLM 驱动的知识助手
- 使用 DeepSeek API
- 基于 Obsidian Vault
- 测试日期：{date.today()}
"""
    test_page = f"test-query-{date.today()}.md"
    write_wiki_note(
        f"sources/{test_page}",
        test_content,
        metadata={
            "type": "source",
            "title": f"Query测试页-{date.today()}",
            "date": str(date.today()),
            "tags": ["测试"],
        },
    )

    # 执行 query
    result = await agent.query(
        "Nemsy 使用什么 API？", archive=False, stream=False  # 不归档，只测试查询
    )

    # 验证返回了答案
    assert result is not None
    assert len(result) > 10
    # 答案应该包含 DeepSeek 相关内容（因为测试页面中有）
    assert "DeepSeek" in result or "API" in result or "暂无" in result

    print(f"\n✓ Query 测试通过")
    print(f"  问题：Nemsy 使用什么 API？")
    print(f"  答案预览：{result[:100]}...")


@pytest.mark.asyncio
async def test_query_with_archive():
    """测试 query 的归档功能。"""
    question = f"测试归档问题-{date.today()}"

    # 执行带归档的 query
    result = await agent.query(question, archive=True, stream=False)

    # 验证返回了答案
    assert result is not None

    # 验证归档文件是否生成（在 queries/ 目录下）
    queries_dir = settings.vault.wiki_path / settings.vault.wiki_queries_dir
    query_files = list(queries_dir.glob(f"*{date.today()}.md"))

    # 应该至少有一个今天的归档文件
    assert len(query_files) > 0

    # 读取最新的归档文件并验证
    latest_query = max(query_files, key=lambda p: p.stat().st_mtime)
    note_text = read_wiki_note(latest_query.relative_to(settings.vault.wiki_path))
    assert note_text is not None
    note = frontmatter.loads(note_text)

    assert note.metadata["type"] == "query"
    assert "title" in note.metadata
    assert len(note.content.strip()) > 0

    print(f"\n✓ Query 归档测试通过")
    print(f"  归档文件：{latest_query.name}")


if __name__ == "__main__":
    # 支持直接运行：python tests/test_smoke.py
    import asyncio

    print("=" * 60)
    print("Nemsy 烟雾测试 - 开始")
    print("=" * 60)

    async def run_all():
        import tempfile

        # Test 1: Ingest
        print("\n[1/3] 测试 ingest...")
        content = """# 测试文章：AI 时代的知识管理
## 核心观点
在 AI 时代，个人知识管理的关键不在于存储更多信息，而在于建立知识之间的关联。
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write(content)
            temp_path = Path(f.name)

        try:
            await test_ingest_basic(temp_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

        # Test 2: Query basic
        print("\n[2/3] 测试 query...")
        await test_query_basic()

        # Test 3: Query with archive
        print("\n[3/3] 测试 query 归档...")
        await test_query_with_archive()

    asyncio.run(run_all())

    print("\n" + "=" * 60)
    print("✓ 所有测试通过！")
    print("=" * 60)
    print("\n⚠️  提醒：测试生成的 Wiki 内容需要手动清理：")
    print(f"   - {settings.vault.wiki_path / 'sources'}/test-*")
    print(f"   - {settings.vault.wiki_path / settings.vault.wiki_queries_dir}/*{date.today()}.md")
