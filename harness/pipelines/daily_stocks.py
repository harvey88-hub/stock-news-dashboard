"""
pipelines/daily_stocks.py
==========================
매일 1회 실행되는 KRX 상장 종목 업데이트 파이프라인.
기존 fetch_stocks.py를 파이프라인으로 래핑합니다.
"""

from __future__ import annotations
from core.logging import PipelineLogger
from core.errors import CollectorError


class DailyStocksPipeline:
    """
    일간 종목 업데이트 파이프라인.

    Harness가 아래 의존성을 주입합니다:
    - collectors["krx"]: KrxCollector
    - store:             Store
    """

    name = "daily_stocks"

    def __init__(self, collectors, analyzers, store, config):
        self._krx    = collectors["krx"]
        self._store  = store
        self._config = config

    def execute(self, dry_run: bool = False, plog: PipelineLogger | None = None) -> dict:
        """
        파이프라인을 실행합니다.

        Returns:
            {"collected": int, "saved": int}
        """
        log = plog or PipelineLogger(self.name)
        summary = {"collected": 0, "saved": 0}

        # ── Step 1: KRX 종목 수집 ─────────────────────────
        log.step("KRX 상장 종목 수집 중 (KOSPI + KOSDAQ)...")
        try:
            stocks = self._krx.collect_stocks()
        except CollectorError as e:
            log.error("KRX 수집 실패", exc=e)
            return summary

        summary["collected"] = len(stocks)
        log.success(f"{len(stocks)}개 종목 수집 완료")

        # ── Step 2: 저장 ──────────────────────────────────
        if not dry_run:
            log.step(f"{len(stocks)}개 종목 저장 중...")
            saved = self._store.save_stocks(stocks)
            summary["saved"] = saved
            log.success(f"{saved}개 저장 완료")
        else:
            log.step("[dry-run] 저장 스킵")

        return summary
