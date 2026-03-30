"""
core/harness.py
===============
Harness 오케스트레이터.
설정을 받아 Collector / Analyzer / Store를 조립하고
파이프라인을 실행합니다.
"""

from __future__ import annotations
from typing import Callable

from .config import AppConfig, load_config
from .interfaces import Collector, Analyzer, Store
from .logging import get_logger, PipelineLogger
from .errors import ConfigError, PipelineError


class Harness:
    """
    파이프라인 실행 엔진.

    사용 예::

        harness = Harness.from_config()
        harness.register_collector("rss", rss_col)
        harness.register_analyzer("claude", claude_ana)
        harness.set_store(supabase_store)
        harness.run_pipeline("hourly_news")
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self._collectors: dict[str, Collector] = {}
        self._analyzers:  dict[str, Analyzer]  = {}
        self._store:      Store | None          = None
        self._pipelines:  dict[str, Callable]  = {}
        self._log = get_logger("harness")

    # ──────────────────────────────────────
    # 팩토리
    # ──────────────────────────────────────

    @classmethod
    def from_config(cls, config_path=None) -> "Harness":
        """설정 파일을 읽어 Harness를 초기화합니다."""
        config = load_config(config_path)
        return cls(config)

    @classmethod
    def with_defaults(cls) -> "Harness":
        """
        기본 설정으로 모든 컴포넌트를 자동 조립합니다.
        환경 변수(SUPABASE_URL, ANTHROPIC_API_KEY 등)가 설정되어 있어야 합니다.
        """
        harness = cls.from_config()
        harness._auto_assemble()
        return harness

    def _auto_assemble(self):
        """환경에 따라 적절한 구현체를 자동 선택하여 등록합니다."""
        from collectors.rss_collector import RssCollector
        from collectors.krx_collector import KrxCollector
        from analyzers.claude_analyzer import ClaudeAnalyzer
        from analyzers.stock_matcher import StockMatcher

        self.register_collector("rss", RssCollector(self.config))
        self.register_collector("krx", KrxCollector(self.config))
        self.register_analyzer("claude", ClaudeAnalyzer(self.config))
        self.register_analyzer("stock_matcher", StockMatcher(self.config))

        # Store: SUPABASE_URL이 있으면 Supabase, 없으면 SQLite(로컬 개발)
        if self.config.supabase_url and self.config.supabase_key:
            from stores.supabase_store import SupabaseStore
            self.set_store(SupabaseStore(self.config))
            self._log.info("Store: Supabase")
        else:
            from stores.sqlite_store import SQLiteStore
            self.set_store(SQLiteStore(self.config))
            self._log.info("Store: SQLite (로컬 개발 모드)")

        # 파이프라인 등록
        from pipelines.hourly_news import HourlyNewsPipeline
        from pipelines.daily_stocks import DailyStocksPipeline
        self.register_pipeline("hourly_news", HourlyNewsPipeline)
        self.register_pipeline("daily_stocks", DailyStocksPipeline)

    # ──────────────────────────────────────
    # 등록 메서드
    # ──────────────────────────────────────

    def register_collector(self, name: str, collector: Collector) -> "Harness":
        self._collectors[name] = collector
        self._log.info(f"Collector registered: {name}")
        return self

    def register_analyzer(self, name: str, analyzer: Analyzer) -> "Harness":
        self._analyzers[name] = analyzer
        self._log.info(f"Analyzer registered: {name}")
        return self

    def set_store(self, store: Store) -> "Harness":
        self._store = store
        return self

    def register_pipeline(self, name: str, pipeline_cls) -> "Harness":
        self._pipelines[name] = pipeline_cls
        return self

    # ──────────────────────────────────────
    # 실행
    # ──────────────────────────────────────

    def run_pipeline(self, name: str, dry_run: bool = False) -> dict:
        """
        파이프라인을 실행하고 결과 요약을 반환합니다.

        Args:
            name:    파이프라인 이름 (예: "hourly_news")
            dry_run: True이면 실제 저장 없이 시뮬레이션만 수행

        Returns:
            {"collected": int, "analyzed": int, "saved": int, ...}
        """
        if name not in self._pipelines:
            available = list(self._pipelines.keys())
            raise PipelineError(name, "init", f"알 수 없는 파이프라인. 사용 가능: {available}")

        if self._store is None:
            raise ConfigError("Store가 설정되지 않았습니다. set_store()를 먼저 호출하세요.")

        pipeline_cls = self._pipelines[name]
        pipeline     = pipeline_cls(
            collectors=self._collectors,
            analyzers=self._analyzers,
            store=self._store,
            config=self.config,
        )

        plog = PipelineLogger(name)
        plog.start()

        try:
            result = pipeline.execute(dry_run=dry_run, plog=plog)
            plog.finish(str(result))
            return result
        except Exception as e:
            plog.error(f"파이프라인 실패", exc=e)
            raise

    def get_store(self) -> Store:
        """현재 등록된 Store를 반환합니다. UI 레이어에서 데이터 조회에 사용합니다."""
        if self._store is None:
            raise ConfigError("Store가 설정되지 않았습니다.")
        return self._store
