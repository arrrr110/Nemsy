# Nemsy Frontend MVP 设计文档

> 版本：v0.1-design  
> 上位文档：MVP.md  
> 目标：以最小代价将 CLI Agent 能力包装为本地 Web UI，保留流式输出体验，降低使用门槛

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

```
┌─────────────────────────────────────────────┐
│  导航栏：Chat | 文件库 | 状态 | 设置          │
├─────────────────────────────────────────────┤
│                                             │
│              当前视图内容区                   │
│                                             │
└─────────────────────────────────────────────┘
```

### 视图一：Chat（默认视图）

- 对话气泡布局，用户输入框在底部
- LLM 回复流式逐字渲染（SSE）
- 顶部切换按钮：**Chat 模式** / **Query 模式**
  - Chat 模式：对话有历史记忆（session 内）
  - Query 模式：每次独立查询，基于 Wiki，等同 `nemsy query`
- 工具栏按钮（对话框右侧或底部）：
  - 📥 **Ingest**：弹出文件/目录选择器，触发摄取
  - 💾 **Save**：等同 `/save`，将当前对话归档为洞见
  - 🔍 **Lint**：触发 Wiki 健康检查，结果在对话流中展示

### 视图二：文件库

左右分栏：
- 左：**原始资料（Sources）** 目录树，每个文件带状态徽章（new / done / changed / empty）
  - 点击文件：右侧预览文件内容
  - 右键文件：触发单文件 Ingest
  - 顶部按钮：**全量扫描摄取**
- 右：**Wiki** 目录树（只读展示）
  - 点击文件：右侧预览 Wiki 页面（Markdown 渲染）

### 视图三：状态（Status）

将 `nemsy status` 的输出结构化展示，分四块卡片：
- Vault 路径 & 状态
- Wiki 页面统计（总数、sources/queries/insights 分布）
- LLM 配置 & 余额
- Token 消耗摘要（累计调用、总 token、按指令/模型饼图或条形图）

### 视图四：设置（Settings）

表单形式，直接读写 `config/settings.toml` 和 `.env`：
- DeepSeek API Key（脱敏显示）
- 知识库根目录路径
- 原始资料子目录名
- Wiki 子目录名
- 默认模型 / 推理模型
- 保存后热重载配置（无需重启服务）

---

## 五、后端 API 设计（草案）

```
POST /api/chat          # Chat 模式单轮，SSE 流式返回
POST /api/query         # Query 模式，SSE 流式返回
POST /api/ingest        # 摄取单文件或目录
POST /api/lint          # Wiki 健康检查，SSE 流式返回
POST /api/save          # 归档当前对话为洞见

GET  /api/status        # 等同 nemsy status，返回 JSON
GET  /api/sources       # 文件树 + 状态，返回 JSON
GET  /api/wiki          # Wiki 目录树，返回 JSON
GET  /api/file          # 读取单个文件内容（sources 或 wiki）

GET  /api/settings      # 读取当前配置
POST /api/settings      # 更新配置并热重载
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

### Phase 1：基础可用（本地 Chat）

- [ ] `nemsy init` 交互式初始化命令
- [ ] `nemsy web` 启动命令（uvicorn + 自动打开浏览器）
- [ ] FastAPI 基础框架（`src/nemsy/web.py`）
- [ ] SSE 流式接口：`/api/chat`、`/api/query`
- [ ] React 前端脚手架（Vite + TypeScript）
- [ ] Chat 视图（流式渲染 + Chat/Query 模式切换）
- [ ] Status 视图（静态 JSON 展示）

### Phase 2：文件库 & Ingest

- [ ] `/api/sources`、`/api/wiki` 目录树接口
- [ ] 文件库视图（Sources + Wiki 双栏）
- [ ] 前端触发 Ingest（单文件 + 目录）
- [ ] `/api/file` 文件内容预览接口
- [ ] Markdown 渲染（Wiki 页面预览）

### Phase 3：完整功能

- [ ] Settings 视图（配置读写 + 热重载）
- [ ] `/save`、`/lint` 前端入口
- [ ] Token 消耗可视化（Status 视图图表）
- [ ] 开发/生产模式构建流程打通

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
