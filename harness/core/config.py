"""
core/config.py
==============
YAML 설정 파일을 로드하고 dataclass로 변환합니다.
환경 변수를 자동으로 오버라이드합니다.
"""

from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore


# ──────────────────────────────────────────
# 설정 dataclass 트리
# ──────────────────────────────────────────

@dataclass
class RssFeed:
    name: str
    url: str
    category: str = "general"


@dataclass
class RssCollectorConfig:
    hours_back: int = 1
    max_articles: int = 1000
    timeout_seconds: int = 10
    user_agent: str = "Mozilla/5.0"
    feeds: list[RssFeed] = field(default_factory=list)


@dataclass
class KrxCollectorConfig:
    base_url: str = "https://apis.data.go.kr/1160100/service/GetKrxListedInfoService/getItemInfo"
    batch_size: int = 3000
    markets: list[str] = field(default_factory=lambda: ["KOSPI", "KOSDAQ"])


@dataclass
class ClaudeModelConfig:
    model: str = "claude-haiku-4-5"
    max_tokens: int = 300
    role: str = ""


@dataclass
class ClaudeAnalyzerConfig:
    screening: ClaudeModelConfig = field(default_factory=ClaudeModelConfig)
    deep_analysis: ClaudeModelConfig = field(
        default_factory=lambda: ClaudeModelConfig(model="claude-sonnet-4-5", max_tokens=900)
    )
    stock_fallback: ClaudeModelConfig = field(default_factory=ClaudeModelConfig)


@dataclass
class StoreConfig:
    default: str = "supabase"
    supabase_tables: dict = field(default_factory=lambda: {
        "articles": "news_articles",
        "analyses": "timeline_issues",
        "stocks":   "listed_stocks",
    })
    supabase_batch_size: int = 500
    sqlite_path: str = "local_dev.db"


@dataclass
class AppConfig:
    """전체 애플리케이션 설정"""
    app_name: str = "트랜드AI"
    timezone: str = "Asia/Seoul"
    hours_back: int = 24

    rss: RssCollectorConfig = field(default_factory=RssCollectorConfig)
    krx: KrxCollectorConfig = field(default_factory=KrxCollectorConfig)
    claude: ClaudeAnalyzerConfig = field(default_factory=ClaudeAnalyzerConfig)
    store: StoreConfig = field(default_factory=StoreConfig)

    # 환경 변수에서 로드 (설정 파일에 넣지 않음)
    supabase_url: str = ""
    supabase_key: str = ""
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    krx_api_key: str = ""


# ──────────────────────────────────────────
# 로더
# ──────────────────────────────────────────

def load_config(config_path: str | Path | None = None) -> AppConfig:
    """
    YAML 파일을 로드하여 AppConfig를 반환합니다.
    환경 변수(SUPABASE_URL, ANTHROPIC_API_KEY 등)가 자동으로 주입됩니다.

    config_path가 None이면 이 파일 기준 ../../config/default.yaml을 탐색합니다.
    """
    raw: dict = {}

    # 1) YAML 로드
    if config_path is None:
        config_path = Path(__file__).parent.parent / "config" / "default.yaml"

    config_path = Path(config_path)
    if config_path.exists() and yaml is not None:
        with open(config_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    # 2) AppConfig 빌드
    cfg = AppConfig()

    app_raw = raw.get("app", {})
    cfg.app_name  = app_raw.get("name", cfg.app_name)
    cfg.timezone  = app_raw.get("timezone", cfg.timezone)
    cfg.hours_back = app_raw.get("hours_back", cfg.hours_back)

    # RSS
    rss_raw = raw.get("collectors", {}).get("rss", {})
    cfg.rss = RssCollectorConfig(
        hours_back=rss_raw.get("hours_back", 1),
        max_articles=rss_raw.get("max_articles", 1000),
        timeout_seconds=rss_raw.get("timeout_seconds", 10),
        user_agent=rss_raw.get("user_agent", "Mozilla/5.0"),
        feeds=[
            RssFeed(name=f["name"], url=f["url"], category=f.get("category", "general"))
            for f in rss_raw.get("feeds", [])
        ],
    )

    # KRX
    krx_raw = raw.get("collectors", {}).get("krx", {})
    cfg.krx = KrxCollectorConfig(
        base_url=krx_raw.get("base_url", cfg.krx.base_url),
        batch_size=krx_raw.get("batch_size", 3000),
        markets=krx_raw.get("markets", ["KOSPI", "KOSDAQ"]),
    )

    # Claude Analyzer
    cl_raw = raw.get("analyzers", {}).get("claude", {})
    cfg.claude = ClaudeAnalyzerConfig(
        screening=ClaudeModelConfig(**{k: v for k, v in cl_raw.get("screening", {}).items() if k != "role"},
                                     role=cl_raw.get("screening", {}).get("role", "")),
        deep_analysis=ClaudeModelConfig(**{k: v for k, v in cl_raw.get("deep_analysis", {}).items() if k != "role"},
                                         role=cl_raw.get("deep_analysis", {}).get("role", "")),
        stock_fallback=ClaudeModelConfig(**{k: v for k, v in cl_raw.get("stock_fallback", {}).items() if k != "role"},
                                          role=cl_raw.get("stock_fallback", {}).get("role", "")),
    )

    # Store
    st_raw = raw.get("stores", {})
    cfg.store = StoreConfig(
        default=st_raw.get("default", "supabase"),
        supabase_tables=st_raw.get("supabase", {}).get("tables", cfg.store.supabase_tables),
        supabase_batch_size=st_raw.get("supabase", {}).get("batch_size", 500),
        sqlite_path=st_raw.get("sqlite", {}).get("path", "local_dev.db"),
    )

    # 3) 환경 변수 오버라이드 (비밀값은 절대 YAML에 넣지 않음)
    cfg.supabase_url      = os.environ.get("SUPABASE_URL", "")
    cfg.supabase_key      = os.environ.get("SUPABASE_KEY", "")
    cfg.anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    cfg.openai_api_key    = os.environ.get("OPENAI_API_KEY", "")
    cfg.krx_api_key       = os.environ.get("KRX_API_KEY", "")

    return cfg
