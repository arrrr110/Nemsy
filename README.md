# 奈姆希（Nemsy）：一个自我构建的私人知识助理

> 名字取自炉石传说中的 Nemsy Necrofizzle —— 聪明、好奇、充满能量。

本项目基于 Karpathy 的 LLM Wiki 理念，由 DeepSeek 超长上下文模型驱动，以 Obsidian Vault 为知识源，为唯一用户提供持续积累、自主归纳的个人知识服务。

详情请查看 [LLM Wiki 理念（中文）](karpathy-idea-zh.md)

---

## 目录结构

```
Nemsy/
├── src/nemsy/
│   ├── __init__.py
│   ├── cli.py          # CLI 入口（click + rich）
│   ├── agent.py        # Agent 核心：ingest / query / lint / chat
│   ├── vault.py        # Obsidian Vault 读写操作
│   ├── llm.py          # DeepSeek API 封装（流式 / 普通 / 推理）
│   └── config.py       # 统一配置加载（.env + settings.toml）
├── config/
│   └── settings.toml   # 项目配置（Vault 路径、模型、CLI 等）
├── tests/
├── .catpaw/
│   └── rules           # Vibe coding 规则（AI 协作约定）
├── .env                # 密钥（不进 git）
├── .env.example        # 密钥模板
└── pyproject.toml      # 包配置与依赖管理
```

Obsidian Vault 内由 Nemsy 管理的目录：

```
Obsidian Vault/
├── nemsy-wiki/         # Wiki 层（由 LLM 写，你来读）
│   ├── AGENTS.md       # Nemsy 行为规范（Schema 配置文件）
│   ├── index.md        # 内容索引
│   ├── log.md          # 操作日志（仅追加）
│   ├── sources/        # 摄取资料的摘要页面
│   ├── queries/        # 有价值的查询结果归档
│   ├── entities/       # 实体页面（人物、项目、工具）
│   └── concepts/       # 概念页面（理论、方法论）
└── origin-resource/    # 原始资料层（只读，你来维护）
```

---

## 部署

**前置要求：** Python 3.11+、DeepSeek API Key

**1. 克隆项目**

```bash
git clone <repo-url>
cd Nemsy
```

**2. 创建虚拟环境**

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
```

**3. 安装依赖**

```bash
pip install -e ".[dev]"
```

**4. 配置密钥**

```bash
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY
```

**5. 配置 Vault 路径**

编辑 `config/settings.toml`，修改 `[vault]` 下的 `path` 为你的 Obsidian Vault 路径：

```toml
[vault]
path = "/your/path/to/Obsidian Vault"
raw_sources_dir = ""   # 原始资料子目录，整理后填入
```

**6. macOS 磁盘访问权限（Vault 在 iCloud / OneDrive 时必须）**

> 系统设置 → 隐私与安全性 → 完全磁盘访问权限 → 添加终端应用并开启

**7. 验证配置**

```bash
nemsy status
```

---

## CLI 使用

### 查看状态

```bash
nemsy status
```

显示 Vault 路径、Wiki 页面统计、LLM 配置等信息。

### 对话模式（默认）

```bash
nemsy
# 或
nemsy chat
```

进入持续对话，支持对话内命令：

| 命令 | 说明 |
|------|------|
| `/ingest <文件路径>` | 摄取本地文件进 Wiki |
| `/query <问题>` | 向 Wiki 提问 |
| `/lint` | 运行 Wiki 健康检查 |
| `/status` | 查看当前状态 |
| `/help` | 显示帮助 |
| `/quit` | 退出 |

### 摄取资料

```bash
nemsy ingest "/path/to/article.md"
nemsy ingest "/path/to/article.md" --title "自定义标题"
```

读取 Markdown 文件，由 LLM 提取关键信息并整合进 Wiki，自动写入摘要页面、更新 index.md 和 log.md。

### 提问查询

```bash
nemsy query "LLM Wiki 的核心理念是什么？"
nemsy query "Ingest 和 RAG 有什么区别？" --archive   # 归档答案为 Wiki 页面
nemsy query "如何构建个人知识体系？" --reason         # 使用深度推理模型
```

### Wiki 健康检查

```bash
nemsy lint
```

检查 Wiki 中的矛盾、孤立页面、缺失引用等问题，并给出改进建议。
