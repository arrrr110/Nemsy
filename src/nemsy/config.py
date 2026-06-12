"""Nemsy 配置加载模块。

加载优先级（高 → 低）：
  1. 环境变量
  2. .env 文件
  3. config/settings.toml
  4. 代码中的默认值
"""

from pathlib import Path

import tomllib
from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

# 项目根目录（src/nemsy/config.py → 上三级）
_PROJECT_ROOT = Path(__file__).parent.parent.parent
_TOML_PATH = _PROJECT_ROOT / "config" / "settings.toml"


def _load_toml() -> dict:
    """读取 config/settings.toml，文件不存在时返回空字典。"""
    if _TOML_PATH.exists():
        with open(_TOML_PATH, "rb") as f:
            return tomllib.load(f)
    return {}


# 全局 toml 数据，模块加载时读取一次
_toml = _load_toml()


class Settings(BaseSettings):
    """Nemsy 全局配置，统一从 .env 和 settings.toml 加载。"""

    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Vault ──────────────────────────────────────────────
    vault_path: Path = Field(
        default=Path(_toml.get("vault", {}).get(
            "path",
            "/Users/ppp/Library/CloudStorage/OneDrive-个人/文档/Obsidian Vault",
        )),
        alias="NEMSY_VAULT_PATH",
        description="Obsidian Vault 根目录",
    )
    vault_wiki_dir: str = Field(
        default=_toml.get("vault", {}).get("wiki_dir", "nemsy-wiki"),
        alias="NEMSY_VAULT_WIKI_DIR",
    )
    vault_raw_sources_dir: str = Field(
        default=_toml.get("vault", {}).get("raw_sources_dir", ""),
        alias="NEMSY_VAULT_RAW_SOURCES_DIR",
    )
    vault_raw_sources_ignore: list[str] = Field(
        default=_toml.get("vault", {}).get("raw_sources_ignore", []),
        description="origin-sources 内部黑名单，列出不需要摄取的子目录名",
    )

    # ── LLM ───────────────────────────────────────────────
    # 优先读 DEEPSEEK_API_KEY（.env 中配置），兼容 ANTHROPIC_API_KEY
    deepseek_api_key: str = Field(
        default="",
        alias="DEEPSEEK_API_KEY",
        description="DeepSeek API Key（通过 DEEPSEEK_API_KEY 或 ANTHROPIC_API_KEY 环境变量传入）",
    )
    llm_base_url: str = Field(
        default=_toml.get("llm", {}).get("base_url", "https://api.deepseek.com"),
        alias="NEMSY_LLM_BASE_URL",
    )
    llm_default_model: str = Field(
        default=_toml.get("llm", {}).get("default_model", "deepseek-v4-flash"),
        alias="NEMSY_LLM_DEFAULT_MODEL",
    )
    llm_reasoning_model: str = Field(
        default=_toml.get("llm", {}).get("reasoning_model", "deepseek-v4-pro"),
        alias="NEMSY_LLM_REASONING_MODEL",
    )
    llm_max_tokens: int = Field(
        default=_toml.get("llm", {}).get("max_tokens", 8192),
    )
    llm_temperature: float = Field(
        default=_toml.get("llm", {}).get("temperature", 0.7),
    )

    # ── Memory ────────────────────────────────────────────
    memory_history_dir: Path = Field(
        default=_PROJECT_ROOT / ".nemsy" / "history",
    )
    memory_summary_cache_dir: Path = Field(
        default=_PROJECT_ROOT / ".nemsy" / "cache",
    )
    memory_max_turns: int = Field(
        default=_toml.get("memory", {}).get("max_turns", 0),
    )

    # ── CLI ───────────────────────────────────────────────
    cli_theme_color: str = Field(
        default=_toml.get("cli", {}).get("theme_color", "cyan"),
    )
    cli_show_welcome: bool = Field(
        default=_toml.get("cli", {}).get("show_welcome", True),
    )

    # ── 计算属性（保持对外接口不变）───────────────────────

    @computed_field  # type: ignore[prop-decorator]
    @property
    def vault(self) -> "_VaultProxy":
        return _VaultProxy(self)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def llm(self) -> "_LLMProxy":
        return _LLMProxy(self)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def memory(self) -> "_MemoryProxy":
        return _MemoryProxy(self)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def cli(self) -> "_CLIProxy":
        return _CLIProxy(self)

    def ensure_dirs(self) -> None:
        """确保运行时所需目录存在。"""
        self.vault.wiki_path.mkdir(parents=True, exist_ok=True)
        self.memory_history_dir.mkdir(parents=True, exist_ok=True)
        self.memory_summary_cache_dir.mkdir(parents=True, exist_ok=True)


class _VaultProxy:
    """Vault 配置的只读代理，保持 settings.vault.xxx 访问方式。"""

    def __init__(self, s: Settings) -> None:
        self._s = s

    @property
    def path(self) -> Path:
        return self._s.vault_path

    @property
    def wiki_dir(self) -> str:
        return self._s.vault_wiki_dir

    @property
    def wiki_path(self) -> Path:
        return self._s.vault_path / self._s.vault_wiki_dir

    @property
    def raw_sources_dir(self) -> str:
        return self._s.vault_raw_sources_dir

    @property
    def raw_sources_path(self) -> Path | None:
        if self._s.vault_raw_sources_dir:
            return self._s.vault_path / self._s.vault_raw_sources_dir
        return None

    @property
    def raw_sources_ignore(self) -> list[str]:
        """origin-sources 内部黑名单，列出不需要摄取的子目录名。"""
        return self._s.vault_raw_sources_ignore

    # ── Wiki 子目录名（集中定义，避免硬编码散落各处）────────

    @property
    def wiki_sources_dir(self) -> str:
        """Wiki 摘要页子目录名（外部资料摘要）。"""
        return "sources"

    @property
    def wiki_insights_dir(self) -> str:
        """Wiki 洞见页子目录名（chat 对话中涌现的共同创造观点）。"""
        return "insights"

    @property
    def wiki_queries_dir(self) -> str:
        """Wiki 查询归档子目录名（单次 query 结果）。"""
        return "queries"

    @property
    def wiki_index_file(self) -> str:
        """Wiki 全局索引文件名。"""
        return "index.md"

    @property
    def wiki_log_file(self) -> str:
        """Wiki 操作日志文件名。"""
        return "log.md"


class _LLMProxy:
    """LLM 配置的只读代理。"""

    def __init__(self, s: Settings) -> None:
        self._s = s

    @property
    def api_key(self) -> str:
        return self._s.deepseek_api_key

    @property
    def base_url(self) -> str:
        return self._s.llm_base_url

    @property
    def default_model(self) -> str:
        return self._s.llm_default_model

    @property
    def reasoning_model(self) -> str:
        return self._s.llm_reasoning_model

    @property
    def max_tokens(self) -> int:
        return self._s.llm_max_tokens

    @property
    def temperature(self) -> float:
        return self._s.llm_temperature


class _MemoryProxy:
    """Memory 配置的只读代理。"""

    def __init__(self, s: Settings) -> None:
        self._s = s

    @property
    def history_dir(self) -> Path:
        return self._s.memory_history_dir

    @property
    def summary_cache_dir(self) -> Path:
        return self._s.memory_summary_cache_dir

    @property
    def max_turns(self) -> int:
        return self._s.memory_max_turns


class _CLIProxy:
    """CLI 配置的只读代理。"""

    def __init__(self, s: Settings) -> None:
        self._s = s

    @property
    def theme_color(self) -> str:
        return self._s.cli_theme_color

    @property
    def show_welcome(self) -> bool:
        return self._s.cli_show_welcome


# 全局单例
settings = Settings()
