# Nemsy Frontend MVP 设计文档

> 版本：v0.2  
> 上位文档：MVP.md  
> 目标：以最小代价将 CLI Agent 能力包装为本地 Web UI，保留流式输出体验，降低使用门槛  
> 最后更新：2026-06-21

---

## 一、设计原则

```
CLI 层（已有）
    ↓  薄 API 层（新增，不重写业务）
Web 前端（新增，映射 CLI 功能）
```

- **后端不重写业务**：`agent.py` 的所有核心逻辑保持不动，Web 后端只是将其暴露为 HTTP/SSE 接口
- **流式输出是必须项**：LLM 逐字输出是核心体验，Web 版通过 SSE（Server-Sent Events）保留
- **Obsidian 非必需**：`nemsy init` 引导用户指定任意本地文件夹作为知识库根目录，彻底解耦 Obsidian 依赖
- **本地优先**：Web UI 只服务 localhost，无需部署，无需账号体系

---

## 二、技术选型

| 层 | 选型 | 理由 |
|----|------|------|
| 后端 | **FastAPI** | 异步原生支持（与现有 asyncio 代码无缝对接）、SSE 原生支持、轻量 |
| 前端 | **React + Vite** | 生态成熟、流式渲染支持好、构建产物可直接由 FastAPI 托管静态文件 |
| 启动方式 | `nemsy web` 命令 | 一行命令启动 FastAPI 服务 + 自动打开浏览器，无 Electron 依赖 |
| 通信 | HTTP REST + SSE | 普通操作用 REST，LLM 流式输出用 SSE |

> **放弃 Electron 的理由**：打包复杂（需 Node 环境）、体积大（100MB+）、与现有 Python 栈异构。本地 `localhost` 网页在体验上与 Electron 几乎无差别，但维护成本低得多。

---

## 三、新增命令

### `nemsy init`

交互式初始化向导，面向首次使用的用户：

```
$ nemsy init

欢迎使用 Nemsy！进行初始化配置。

? 请输入你的 DeepSeek API Key: sk-xxx...
? 请输入知识库根目录路径（Obsidian Vault 或任意文件夹）: /Users/me/my-knowledge
? 请输入原始资料子目录名（留空使用默认 origin-sources）: 
? 请输入 Wiki 子目录名（留空使用默认 nemsy-wiki）: 

✓ 已写入 .env
✓ 已写入 config/settings.toml
✓ 初始化完成！运行 nemsy web 启动界面，或 nemsy 直接进入 CLI。
```

实现：写入 `.env`（API Key）和 `config/settings.toml`（路径配置），不影响已有配置逻辑。

---

### `nemsy web`

```bash
nemsy web           # 启动本地 Web 服务，默认端口 7860
nemsy web --port 8080
nemsy web --no-open  # 不自动打开浏览器
```

行为：
1. 启动 FastAPI 服务（`uvicorn`）
2. 自动打开 `http://localhost:7860`
3. Ctrl+C 停止

---

## 四、前端视图结构

实际采用**左侧边栏导航 + 右侧内容区**布局（Obsidian 风格），替代原顶部导航栏方案。

```
┌────────────┬──────────────────────────────────────┐
│  Sidebar   │           Main Content               │
│  ──────    │  ┌────────────────────────────────┐  │
│  💬 Chat   │  │ Header（标题 + 模式切换）       │  │
│  📁 文件库  │  ├────────────────────────────────┤  │
│  📊 状态   │  │ 消息流（滚动区）                │  │
│  ⚙️ 设置   │  ├────────────────────────────────┤  │
│            │  │ 输入框 + 发送/停止按钮           │  │
│            │  └────────────────────────────────┘  │
└────────────┴──────────────────────────────────────┘
```

### 视图一：Chat（默认视图）✅ 已完成

- ✅ 对话气泡布局，用户输入框在底部
- ✅ LLM 回复流式逐字渲染（SSE），streaming 光标闪烁
- ✅ 顶部切换按钮：**Chat 模式** / **Wiki 模式**
  - ✅ Chat 模式：多轮对话，携带 session 历史
  - ✅ Wiki 模式：独立查询，基于知识图谱，等同 `nemsy query`
- ✅ Markdown 渲染（加粗、列表、blockquote、代码块）
- ✅ `[[页面名]]` 解析为行内角标，hover 显示 Wiki 标题
- ✅ 气泡底部引用列表，点击跳转对应 Wiki 文件
- ✅ Stop 按钮（生成中可中断）
- ✅ Enter 发送 / Shift+Enter 换行
- ✅ Web Prompt 独立优化：角标引用约束、禁止手动编号、禁止疏离表述
- ⬜ 工具栏按钮：
  - ⬜ 📥 **Ingest**：弹出文件/目录选择器，触发摄取
  - ⬜ 💾 **Save**：将当前对话归档为洞见
  - ⬜ 🔍 **Lint**：触发 Wiki 健康检查

### 视图二：文件库 ✅ 基础完成

左右分栏：
- ✅ 左：Sources / Wiki 双 Tab 切换
- ✅ **原始资料（Sources）** 目录树，每个文件带状态徽章（new / done / changed / empty）
  - ✅ 点击文件：右侧预览文件内容（原始 Markdown）
  - ✅ 顶部过滤搜索框，输入有内容时显示清空按钮（✕）
- ✅ **Wiki** 目录树，按 type 分组展示，每条带 badge
  - ✅ 点击文件：右侧预览 Wiki 页面（Markdown 渲染）
  - ✅ 顶部过滤搜索框（同上）
- ⬜ 右键文件：触发单文件 Ingest
- ⬜ 顶部按钮：全量扫描摄取

### 视图三：状态（Status）✅ 基础完成

- ✅ Vault 路径 & 存在状态
- ✅ Wiki 页面统计（总数、sources/queries 数量）
- ✅ LLM 配置（API Key 状态、模型名、接入点）
- ✅ **DeepSeek 账户余额**：独立异步查询（`/api/balance`），加载中显示 badge，不阻塞主状态数据；展示总余额及充值/赠送明细
- ✅ Token 消耗摘要（累计调用、输入/输出/合计 tokens）
- ✅ 按命令/模型明细展示
- ⬜ Token 消耗可视化图表（饼图或条形图）

### 视图四：设置（Settings）✅ 只读完成

- ✅ `config/settings.toml` 内容展示（递归分组渲染）
- ✅ `.env` 环境变量展示，敏感字段（KEY/TOKEN/SECRET）中段自动脱敏
- ✅ 首次使用引导 Banner：未配置 API Key 时显示，4 步引导用户完成配置
- ✅ `.env` 配置说明 Tips：常驻说明各变量含义及注意事项
- ✅ `.env` 缺失时显示快速创建命令指引
- ⬜ 写操作（表单保存 + 热重载）→ Phase 3

---

## 五、后端 API 设计

```
POST /api/chat          # ✅ Chat 模式多轮，SSE 流式返回（含 history）
POST /api/query         # ✅ Query/Wiki 模式，SSE 流式返回
POST /api/ingest        # ✅ 摄取单文件或目录
POST /api/lint          # ✅ Wiki 健康检查，SSE 流式返回
POST /api/save          # ✅ 归档当前对话为洞见

GET  /api/status        # ✅ 等同 nemsy status，返回 JSON
GET  /api/sources       # ✅ 文件树 + 状态，返回 JSON
GET  /api/wiki          # ✅ Wiki 目录树，返回 JSON
GET  /api/wiki/resolve  # ✅ 按标题解析 Wiki 文件绝对路径（引用跳转用）
GET  /api/file          # ✅ 读取单个文件内容（sources 或 wiki）

GET  /api/balance       # ✅ 异步查询 DeepSeek 账户余额
GET  /api/settings      # ✅ 读取当前配置（TOML + ENV，敏感字段脱敏）
POST /api/settings      # ⬜ 更新配置并热重载
```

SSE 流格式（与现有 `llm.chat_stream` 直接对接）：
```
data: {"type": "chunk", "text": "Hello"}
data: {"type": "chunk", "text": " world"}
data: {"type": "done", "usage": {"prompt_tokens": 100, "completion_tokens": 50}}
```

---

## 六、工程结构（新增部分）

```
Nemsy/
├── src/nemsy/
│   ├── web.py          # FastAPI app + 路由定义（新增）
│   └── ...（现有文件不动）
├── frontend/           # React 前端（新增）
│   ├── src/
│   │   ├── App.tsx
│   │   ├── views/
│   │   │   ├── Chat.tsx
│   │   │   ├── FileLibrary.tsx
│   │   │   ├── Status.tsx
│   │   │   └── Settings.tsx
│   │   └── components/
│   ├── package.json
│   └── vite.config.ts
└── pyproject.toml      # 新增 web 依赖组：fastapi, uvicorn
```

构建流程：
1. `cd frontend && npm run build` → 产物输出到 `frontend/dist/`
2. FastAPI 以静态文件方式托管 `frontend/dist/`
3. 开发模式：Vite dev server 代理 API 请求到 FastAPI

---

## 七、待实现清单

### Phase 1：基础可用（本地 Chat）✅ 已完成

- [x] `nemsy web` 启动命令（uvicorn + 自动打开浏览器）
- [x] FastAPI 基础框架（`src/nemsy/web.py`）
- [x] SSE 流式接口：`/api/chat`（多轮）、`/api/query`
- [x] React 前端脚手架（Vite + TypeScript，Obsidian 深色风格）
- [x] Chat 视图：流式渲染 + Chat/Wiki 模式切换 + Markdown 渲染
- [x] `[[页面名]]` → 行内角标 + 气泡底部引用列表（可点击跳转）
- [x] Web Prompt 独立优化：角标引用约束、禁止疏离表述
- [x] Status 视图：结构化卡片展示 Vault/Wiki/LLM/Token 用量
- [ ] `nemsy init` 交互式初始化命令（暂缓，优先完成 UI）

### Phase 2：文件库 & Ingest ✅ 部分完成

- [x] `/api/sources`、`/api/wiki`、`/api/file`、`/api/wiki/resolve` 后端接口
- [x] 文件库视图：Sources 目录树（带状态徽章）+ Wiki 目录树（按 type 分组）
- [x] 点击文件预览内容（Markdown 渲染，Sources 原始、Wiki 渲染）
- [x] 搜索过滤框 + 有内容时显示清空按钮
- [x] Status 页 API 余额独立异步加载（`/api/balance`）
- [x] Settings 视图只读完成（TOML + ENV 展示 + 首次引导）
- [x] 侧边栏折叠/展开（动画过渡，折叠后图标模式）
- [x] 架构清理：余额查询逻辑提取到 `llm.py`（`fetch_balance` / `fetch_balance_async`），CLI 和 Web 共用
- [ ] 前端触发 Ingest（单文件 + 目录）
- [ ] Chat 工具栏：📥 Ingest / 💾 Save / 🔍 Lint 按钮

### Phase 3：完整功能 ⬜ 未开始

- [x] `/api/settings` GET 接口（只读，含脱敏）
- [ ] Settings 视图写操作（表单保存 + 热重载）
- [ ] `/api/settings` POST 接口（写配置 + 热重载）
- [ ] Token 消耗可视化图表（Status 视图）
- [ ] 开发/生产模式构建流程打通（`npm run build` → FastAPI 静态托管）

---

## 八、关键决策记录

| 决策 | 选择 | 放弃 | 理由 |
|------|------|------|------|
| 桌面容器 | 浏览器（localhost） | Electron | 无需 Node 打包，Python 栈更纯粹，体验差异可忽略 |
| 后端框架 | FastAPI | Flask / Django | 原生异步，SSE 支持好，与现有 asyncio 代码无缝 |
| 流式协议 | SSE | WebSocket | 单向流场景 SSE 更简单，无需握手维护连接状态 |
| 前端框架 | React + Vite | Vue / Svelte | 生态最大，流式渲染 hook 生态丰富 |
| 配置方式 | `nemsy init` 向导 | 手改 toml | 降低非技术用户门槛，解耦 Obsidian 依赖 |
| 前端托管 | FastAPI 静态文件 | 独立部署 | 单进程单命令，用户无需理解前后端分离 |
