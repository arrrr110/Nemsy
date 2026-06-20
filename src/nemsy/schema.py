"""Nemsy Wiki 页面格式 Schema 定义。

所有 Wiki 页面生成操作必须遵循此规范。
"""

# ---------------------------------------------------------------------------
# Wiki 页面类型
# ---------------------------------------------------------------------------

WIKI_PAGE_TYPES = ["source", "query", "insight", "entity", "concept"]

# ---------------------------------------------------------------------------
# Schema 文本描述（供 LLM prompt 使用）
# ---------------------------------------------------------------------------

WIKI_PAGE_SCHEMA = """
Wiki 页面格式规范（所有写入操作必须遵守）：
每个 Wiki 页面的 frontmatter 必须包含以下字段：
  type: source | query | insight | entity | concept  # 必填，页面类型
  title: "..."                                        # 必填，页面标题
  date: YYYY-MM-DD                                   # 必填，创建日期
  tags: [...]                                        # 推荐，标签列表

各类型额外字段：
  source 类型：source（原始资料路径或来源说明）
  query 类型：无额外必填字段
  insight 类型：source（chat 或 external）
"""

# ---------------------------------------------------------------------------
# 快捷构造函数
# ---------------------------------------------------------------------------

def make_source_metadata(title: str, date: str, source: str, tags: list[str] | None = None) -> dict:
    """构造 source 类型页面的 frontmatter。"""
    return {
        "type": "source",
        "title": title,
        "date": date,
        "source": source,
        "tags": tags or [],
    }


def make_query_metadata(title: str, date: str, tags: list[str] | None = None) -> dict:
    """构造 query 类型页面的 frontmatter。"""
    return {
        "type": "query",
        "title": title,
        "date": date,
        "tags": tags or [],
    }


def make_insight_metadata(title: str, date: str, source: str = "chat", tags: list[str] | None = None) -> dict:
    """构造 insight 类型页面的 frontmatter。
    
    Args:
        title: 洞见标题
        date: 创建日期（YYYY-MM-DD）
        source: 来源，chat 或 external
        tags: 标签列表
    """
    return {
        "type": "insight",
        "title": title,
        "date": date,
        "source": source,
        "tags": tags or [],
    }
