"""Nemsy Web 后端（FastAPI）。

职责：将 agent.py 的核心能力暴露为 HTTP/SSE 接口，
      托管 frontend/dist/ 静态文件（生产模式）。

启动方式：
    nemsy web              # CLI 命令（pyproject.toml 注册）
    uvicorn nemsy.web:app  # 直接启动（开发调试）

端口默认 7860，可通过 --port 参数覆盖。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from nemsy.config import settings

# ---------------------------------------------------------------------------
# FastAPI 实例
# ---------------------------------------------------------------------------

app = FastAPI(title="Nemsy", version="0.1.0", docs_url="/api/docs")

# 开发模式允许 Vite dev server（localhost:5173）跨域访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# SSE 工具函数
# ---------------------------------------------------------------------------

def _sse_chunk(text: str) -> str:
    return f"data: {json.dumps({'type': 'chunk', 'text': text}, ensure_ascii=False)}\n\n"


def _sse_done(prompt_tokens: int = 0, completion_tokens: int = 0) -> str:
    return (
        f"data: {json.dumps({'type': 'done', 'usage': {'prompt_tokens': prompt_tokens, 'completion_tokens': completion_tokens}})}\n\n"
    )


async def _stream_response(gen: AsyncIterator[str], usage_box: object) -> AsyncIterator[str]:
    """将 llm.chat_stream 的迭代器包装为 SSE 格式输出。"""
    async for chunk in gen:
        yield _sse_chunk(chunk)
    # 迭代完成后输出 usage
    box = getattr(usage_box, "usage", None)
    pt = getattr(box, "prompt_tokens", 0)
    ct = getattr(box, "completion_tokens", 0)
    yield _sse_done(pt, ct)


# ---------------------------------------------------------------------------
# 请求体模型
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []


class QueryRequest(BaseModel):
    question: str
    archive: bool = False


class IngestRequest(BaseModel):
    path: str
    recursive: bool = False
    force: bool = False


class SaveRequest(BaseModel):
    history: list[dict]
    topic: str | None = None


class SettingsPayload(BaseModel):
    deepseek_api_key: str | None = None
    vault_path: str | None = None
    vault_wiki_dir: str | None = None
    vault_raw_sources_dir: str | None = None
    llm_default_model: str | None = None
    llm_reasoning_model: str | None = None


# ---------------------------------------------------------------------------
# 路由：状态
# ---------------------------------------------------------------------------

@app.get("/api/balance")
async def api_balance() -> dict:
    """单独的余额查询端点，供前端独立轮询（避免拖慢 /api/status）。"""
    from nemsy import llm
    return await llm.fetch_balance_async()


@app.get("/api/status")
async def api_status() -> dict:
    """返回与 nemsy status 等价的结构化数据。"""
    from nemsy.vault import list_wiki_notes, summarize_token_log

    wiki_path = settings.vault.wiki_path
    wiki_notes = list_wiki_notes()
    v = settings.vault
    sources_count = len(list(wiki_path.glob(f"{v.wiki_sources_dir}/*.md"))) if wiki_path.exists() else 0
    queries_count = len(list(wiki_path.glob(f"{v.wiki_queries_dir}/*.md"))) if wiki_path.exists() else 0

    return {
        "vault": {
            "path": str(settings.vault.path),
            "exists": settings.vault.path.exists(),
            "raw_sources_dir": str(settings.vault.raw_sources_path) if settings.vault.raw_sources_path else None,
        },
        "wiki": {
            "path": str(wiki_path),
            "exists": wiki_path.exists(),
            "total_notes": len(wiki_notes),
            "sources_count": sources_count,
            "queries_count": queries_count,
        },
        "llm": {
            "api_key_set": bool(settings.llm.api_key),
            "base_url": settings.llm.base_url,
            "default_model": settings.llm.default_model,
            "reasoning_model": settings.llm.reasoning_model,
        },
        "token_usage": summarize_token_log(),
    }


# ---------------------------------------------------------------------------
# 路由：文件树
# ---------------------------------------------------------------------------

@app.get("/api/sources")
async def api_sources() -> dict:
    """返回原始资料目录树及每个文件的摄取状态。"""
    from nemsy.vault import collect_files, load_ingest_log
    from datetime import datetime

    raw_path = settings.vault.raw_sources_path
    if not raw_path or not raw_path.exists():
        return {"files": []}

    paths = collect_files(raw_path, recursive=True)
    log_files: dict = load_ingest_log().get("files", {})

    result = []
    for p in paths:
        rel = str(p.relative_to(raw_path))
        key = str(p.resolve())
        record = log_files.get(key)

        if p.stat().st_size == 0:
            status = "empty"
            last_ingested = None
        elif record is None:
            status = "new"
            last_ingested = None
        else:
            ingested_at = record.get("ingested_at", [])
            last_ingested = ingested_at[-1] if ingested_at else None
            if last_ingested:
                try:
                    mtime = datetime.fromtimestamp(p.stat().st_mtime)
                    if mtime > datetime.fromisoformat(last_ingested):
                        status = "changed"
                    else:
                        status = "done"
                except (ValueError, OSError):
                    status = "done"
            else:
                status = "new"

        result.append({
            "path": rel,
            "abs_path": str(p),
            "status": status,
            "last_ingested": last_ingested,
        })

    return {"root": str(raw_path), "files": result}


@app.get("/api/wiki")
async def api_wiki() -> dict:
    """返回 Wiki 目录树（含 frontmatter 元数据）。"""
    from nemsy.vault import list_wiki_notes
    import frontmatter as fm

    wiki_path = settings.vault.wiki_path
    if not wiki_path.exists():
        return {"root": str(wiki_path), "files": []}

    notes = list_wiki_notes()
    result = []
    for p in notes:
        rel = str(p.relative_to(wiki_path))
        try:
            post = fm.load(str(p))
            raw_type  = post.get("type")
            raw_title = post.get("title")
            raw_date  = post.get("date")
            raw_tags  = post.get("tags")
            note_type = str(raw_type)  if raw_type  is not None else ""
            title     = str(raw_title) if raw_title is not None else p.stem
            date      = str(raw_date)  if raw_date  is not None else ""
            tags      = list(raw_tags) if isinstance(raw_tags, (list, tuple)) else []
        except Exception:
            note_type, title, date, tags = "", p.stem, "", []
        result.append({
            "rel_path": rel,
            "abs_path": str(p),
            "type": note_type,
            "title": title,
            "date": date,
            "tags": tags,
        })
    return {"root": str(wiki_path), "files": result}


@app.get("/api/wiki/resolve")
async def api_wiki_resolve(title: str) -> dict:
    """根据 Wiki 页面标题（stem，不含路径和 .md）找到实际文件的绝对路径。
    用于前端点击引用角标后定位文件。
    """
    from nemsy.vault import list_wiki_notes

    wiki_path = settings.vault.wiki_path
    # 规范化查找：去除 .md 后缀、忽略路径前缀、忽略大小写
    target = title.lower().removesuffix(".md")
    for note in list_wiki_notes():
        if note.stem.lower() == target:
            return {"title": title, "abs_path": str(note), "rel_path": str(note.relative_to(wiki_path))}
    raise HTTPException(status_code=404, detail=f"Wiki page not found: {title}")


@app.get("/api/file")
async def api_file(path: str) -> dict:
    """读取单个文件内容（sources 或 wiki）。"""
    p = Path(path)
    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    # 安全检查：只允许读取 Vault 内的文件
    vault = settings.vault.path
    try:
        p.relative_to(vault)
    except ValueError:
        raise HTTPException(status_code=403, detail="Path outside vault")
    return {"path": path, "content": p.read_text(encoding="utf-8")}


# ---------------------------------------------------------------------------
# 路由：LLM 流式（SSE）
# ---------------------------------------------------------------------------

@app.post("/api/chat")
async def api_chat(req: ChatRequest) -> StreamingResponse:
    """Chat 模式多轮对话，SSE 流式返回。"""
    from nemsy import llm
    from nemsy.agent import _BASE_SYSTEM, _load_wiki_context
    from nemsy.vault import append_token_log

    wiki_context = _load_wiki_context(max_files=20)

    _CHAT_MODE_ADDON = """
当前模式：自由对话。

你的角色定位（严格遵守）：
- 你就是这份知识库本身，以管理者的口吻直接表达知识，不要说"根据 Wiki"、"资料显示"、"Wiki 中提到"等疏离表达
- 把知识当成自己的认知直接输出，就像一个博学的朋友在和你聊天，而不是在引用文献
- 用词自信、简洁，避免"可能"、"似乎"等不必要的不确定性修饰——除非确实存在争议

知识边界（严格遵守）：
- 如果知识库中没有相关内容，直接说「这块我还没有记录，建议你另行查阅」
- 禁止用训练知识填补知识库的空白，用户需要的是他自己归纳的知识，不是通用 AI 的推测

引用格式（严格遵守）：
- 在正文中需要标注来源时，直接行内嵌入 [[页面名]]，前端会自动渲染为上标角标
- 禁止在正文外单独列出"引用来源"清单，禁止写 (1)、（1）、[1]、"见参考资料 1"等手动编号
- [[页面名]] 紧跟在引用的具体结论之后，不要独占一行、不要出现在句首
"""
    chat_system_prompt = (
        f"当前 Wiki 摘要：\n{wiki_context}\n\n"
        + (_BASE_SYSTEM + _CHAT_MODE_ADDON).format(wiki_path=settings.vault.wiki_path)
    )

    system, messages = llm.build_messages(chat_system_prompt, req.history, req.message)

    async def generate() -> AsyncIterator[str]:
        stream_iter, usage_box = await llm.chat_stream(system, messages)
        async for chunk in stream_iter:
            yield _sse_chunk(chunk)
        box = usage_box.usage
        append_token_log("chat", box.model, box.prompt_tokens, box.completion_tokens)
        yield _sse_done(box.prompt_tokens, box.completion_tokens)

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/api/query")
async def api_query(req: QueryRequest) -> StreamingResponse:
    """Query/Wiki 模式，SSE 流式返回。"""
    from nemsy import llm
    from nemsy.agent import _BASE_SYSTEM, _load_wiki_context
    from nemsy.vault import append_token_log

    wiki_context = _load_wiki_context()
    user_prompt = f"问题：{req.question}\n\n---知识库内容---\n{wiki_context}"

    _WEB_QUERY_ADDON = """
当前模式：知识库问答。

你的角色定位（严格遵守）：
- 你就是这份知识库本身，直接以第一人称回答，不要说"根据 Wiki"、"资料显示"等疏离表达
- 把知识当成自己的认知输出，语气自信、简洁，像一个博学的朋友在交流
- 如果知识库中没有相关内容，直接说「这块我还没有记录，建议另行查阅」

引用格式（严格遵守）：
- 在正文中需要标注来源时，直接行内嵌入 [[页面名]]，前端会自动渲染为上标角标
- 禁止在正文外单独列出"引用来源"清单，禁止写 (1)、（1）、[1]、"见参考资料 1"等手动编号
- [[页面名]] 紧跟在引用的具体结论之后，不要独占一行、不要出现在句首

知识边界（严格遵守）：
- 只使用知识库内容回答，禁止用训练知识填补知识库的空白
- 不要推测或补全知识库中不存在的信息
"""

    system, messages = llm.build_messages(
        (_BASE_SYSTEM + _WEB_QUERY_ADDON).format(wiki_path=settings.vault.wiki_path),
        [],
        user_prompt,
    )

    async def generate() -> AsyncIterator[str]:
        stream_iter, usage_box = await llm.chat_stream(system, messages)
        async for chunk in stream_iter:
            yield _sse_chunk(chunk)
        box = usage_box.usage
        append_token_log("query", box.model, box.prompt_tokens, box.completion_tokens)
        yield _sse_done(box.prompt_tokens, box.completion_tokens)

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/api/lint")
async def api_lint() -> StreamingResponse:
    """Wiki 健康检查，SSE 流式返回。"""
    from nemsy import llm
    from nemsy.agent import _LINT_SYSTEM, _load_wiki_context
    from nemsy.vault import append_token_log

    wiki_context = _load_wiki_context(max_files=50)
    user_prompt = f"请对以下 Wiki 进行全面健康检查：\n\n---Wiki 内容---\n{wiki_context}"
    system, messages = llm.build_messages(
        _LINT_SYSTEM.format(wiki_path=settings.vault.wiki_path), [], user_prompt
    )

    async def generate() -> AsyncIterator[str]:
        stream_iter, usage_box = await llm.chat_stream(system, messages)
        async for chunk in stream_iter:
            yield _sse_chunk(chunk)
        box = usage_box.usage
        append_token_log("lint", box.model, box.prompt_tokens, box.completion_tokens)
        yield _sse_done(box.prompt_tokens, box.completion_tokens)

    return StreamingResponse(generate(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# 路由：Ingest / Save
# ---------------------------------------------------------------------------

@app.post("/api/ingest")
async def api_ingest(req: IngestRequest) -> dict:
    """触发文件或目录摄取（非流式，后台执行）。"""
    from nemsy.agent import ingest as agent_ingest
    from nemsy.vault import collect_files, find_index_context

    path = Path(req.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {req.path}")

    files = collect_files(path, recursive=req.recursive) if path.is_dir() else [path]
    results = []
    for f in files:
        content = f.read_text(encoding="utf-8")
        index_context = find_index_context(f)
        wiki_page = await agent_ingest(
            content, f.stem,
            source_path=f,
            index_context=index_context,
            stream=False,
        )
        results.append({"file": str(f), "wiki_page": wiki_page})

    return {"ingested": len(results), "results": results}


@app.post("/api/save")
async def api_save(req: SaveRequest) -> dict:
    """将对话历史归档为洞见页。"""
    from nemsy.agent import save_insight

    filename = await save_insight(req.history, topic=req.topic, stream=False)
    return {"wiki_page": filename}


# ---------------------------------------------------------------------------
# 路由：配置
# ---------------------------------------------------------------------------

def _mask_key(value: str) -> str:
    """将 API Key 中段替换为 *，只保留首 4 位和末 4 位。
    例：sk-a1b2c3d4e5f6g7h8 → sk-a****g7h8
    """
    if not value:
        return ""
    if len(value) <= 12:
        return "***已配置***"
    return value[:6] + "*" * (len(value) - 10) + value[-4:]


def _read_env_pairs() -> list[dict]:
    """读取 .env 文件，返回 [{key, raw, masked}] 列表。
    key 中带 KEY/TOKEN/SECRET/PASSWORD 的值自动脱敏。
    """
    env_path = Path(__file__).parent.parent.parent / ".env"
    if not env_path.exists():
        return []
    pairs = []
    sensitive_keywords = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASS")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        is_sensitive = any(kw in k.upper() for kw in sensitive_keywords)
        pairs.append({
            "key": k,
            "value": _mask_key(v) if is_sensitive else v,
            "sensitive": is_sensitive,
        })
    return pairs


def _read_toml_raw() -> dict:
    """读取 config/settings.toml，返回原始字典，不存在时返回空 {}。"""
    toml_path = Path(__file__).parent.parent.parent / "config" / "settings.toml"
    if not toml_path.exists():
        return {}
    try:
        import tomllib
        return tomllib.loads(toml_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


@app.get("/api/settings")
async def api_get_settings() -> dict:
    """读取当前配置（API Key 脱敏），返回结构化 toml 和 .env 条目。"""
    return {
        "toml": _read_toml_raw(),
        "env": _read_env_pairs(),
        # 快捷摘要（兼容旧字段，供状态卡片用）
        "summary": {
            "vault_path": str(settings.vault.path),
            "wiki_dir": settings.vault.wiki_dir,
            "raw_sources_dir": settings.vault.raw_sources_dir,
            "default_model": settings.llm.default_model,
            "reasoning_model": settings.llm.reasoning_model,
            "api_key_masked": _mask_key(settings.llm.api_key),
            "base_url": settings.llm.base_url,
        },
    }


@app.post("/api/settings")
async def api_save_settings(payload: SettingsPayload) -> dict:
    """更新配置文件（settings.toml 和 .env）。"""
    # TODO: Phase 3 实现 — 解析并写回 toml + .env，然后热重载 settings 单例
    return {"ok": True, "message": "配置保存功能待 Phase 3 实现"}


# ---------------------------------------------------------------------------
# 静态文件托管（生产模式）
# ---------------------------------------------------------------------------

_FRONTEND_DIST = Path(__file__).parent.parent.parent / "frontend" / "dist"

if _FRONTEND_DIST.exists():
    # 生产模式：托管构建产物
    app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="static")


# ---------------------------------------------------------------------------
# CLI 入口（由 pyproject.toml 中 nemsy-web 调用）
# ---------------------------------------------------------------------------

def run_web(port: int = 7860, no_open: bool = False) -> None:
    """启动 Web 服务并可选择自动打开浏览器。"""
    import uvicorn
    import webbrowser
    import threading

    url = f"http://localhost:{port}"
    if not no_open:
        # 延迟 1 秒后打开，确保服务已启动
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    print(f"Nemsy Web UI → {url}")
    print("按 Ctrl+C 停止服务")
    uvicorn.run("nemsy.web:app", host="0.0.0.0", port=port, reload=False)
