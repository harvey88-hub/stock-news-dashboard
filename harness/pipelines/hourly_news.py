"""
pipelines/hourly_news.py
=========================
매시간 실행되는 뉴스 수집 + AI 분석 파이프라인.

흐름:
  1. RSS 수집기로 최근 1시간 기사 수집
  2. DB에 기사 저장
  3. Claude 분석기로 시간대별 핵심 이슈 분석
  4. StockMatcher로 종목 검증
  5. 분석 결과 저장

기존 GitHub Actions가 개별 스크립트(rss_collector.py → analyze.py)를
순서대로 호출하던 방식을 하나의 파이프라인으로 통합합니다.
"""

from __future__ import annotations
from datetime import datetime, timezone, timedelta
from core.logging import PipelineLogger
from core.errors import CollectorPartialError

_KST = timezone(timedelta(hours=9))


class HourlyNewsPipeline:
    """
    매시간 뉴스 파이프라인.

    Harness가 아래 의존성을 주입합니다:
    - collectors["rss"]      : RssCollector
    - analyzers["claude"]    : ClaudeAnalyzer
    - analyzers["stock_matcher"]: StockMatcher
    - store                  : Store (Supabase or SQLite)
    """

    name = "hourly_news"

    def __init__(self, collectors, analyzers, store, config):
        self._rss     = collectors["rss"]
        self._claude  = analyzers["claude"]
        self._matcher = analyzers.get("stock_matcher")
        self._store   = store
        self._config  = config

    def execute(self, dry_run: bool = False, plog: PipelineLogger | None = None) -> dict:
        """
        파이프라인을 실행합니다.

        Args:
            dry_run: True이면 DB 저장 없이 시뮬레이션만 수행
            plog:    진행 로그 핸들러

        Returns:
            {"collected": int, "saved_articles": int, "analyzed": int, "saved_analyses": int}
        """
        log = plog or PipelineLogger(self.name)
        summary = {"collected": 0, "saved_articles": 0, "analyzed": 0, "saved_analyses": 0}

        # ── Step 1: RSS 수집 ──────────────────────────────
        log.step("RSS 수집 중...")
        articles = []
        try:
            articles = self._rss.collect(hours_back=self._config.rss.hours_back)
        except CollectorPartialError as e:
            log.warn(f"일부 소스 실패 (계속 진행): {e.failed_sources}")
            articles = getattr(e, "_articles", [])  # 부분 성공한 기사가 있으면 사용
        except Exception as e:
            log.error("RSS 수집 실패", exc=e)
            return summary

        # CollectorPartialError는 예외를 raise하면서 수집된 기사를 잃어버리므로
        # 실제로는 예외 전에 반환된 값을 사용해야 합니다.
        # RssCollector는 예외를 raise하더라도 이미 수집된 기사를 반환하지 않으므로
        # 이 경우를 별도 처리합니다.
        if not articles:
            # 부분 실패 시 store에서 이미 있는 기사로 분석만 진행
            log.warn("수집된 기사 없음 — 저장된 기사로 분석 시도")
            articles = self._store.get_articles(hours_back=self._config.rss.hours_back * 2)

        summary["collected"] = len(articles)
        log.success(f"{len(articles)}건 수집 완료")

        if not articles:
            log.warn("분석할 기사가 없습니다.")
            # 0건 수집 기록: history에서 확인 가능하도록 trace 생성
            current_hour = datetime.now(_KST).strftime("%Y-%m-%d %H:00")
            self._claude.record_no_articles(current_hour)
            traces = self._claude.flush_traces()
            if traces and not dry_run:
                try:
                    self._store.save_traces(traces)
                except Exception as e:
                    log.warn(f"0건 수집 추적 로그 저장 실패: {e}")
            return summary

        # ── Step 2: 기사 저장 ─────────────────────────────
        if not dry_run:
            log.step(f"{len(articles)}건 기사 저장 중...")
            saved = self._store.save_articles(articles)
            summary["saved_articles"] = saved
            log.success(f"{saved}건 저장")
        else:
            log.step("[dry-run] 기사 저장 스킵")

        # ── Step 3: 이미 분석된 시간대 + 최근 헤드라인 확인 ─
        analyzed_hours = self._store.get_analyzed_hours(hours_back=self._config.hours_back)
        try:
            recent_analyses  = self._store.get_analyses(hours_back=self._config.hours_back)
            recent_headlines = [r.headline for r in recent_analyses if r.headline]
        except Exception:
            recent_headlines = []

        # ── Step 4: Claude 분석 ──────────────────────────
        log.step("Claude 시간대별 분석 중...")
        results = self._claude.analyze(
            articles,
            analyzed_hours=analyzed_hours,
            recent_headlines=recent_headlines,
        )
        summary["analyzed"] = len(results)
        log.success(f"{len(results)}개 시간대 분석 완료")

        # ── Step 5: 종목 매칭 ─────────────────────────────
        if results and self._matcher:
            log.step("종목 DB 매칭 중...")
            listed = self._store.get_listed_stocks()
            if listed:
                results = self._matcher.match(results, listed)
                log.success(f"종목 매칭 완료 ({len(listed)}개 종목 DB 사용)")
            else:
                log.warn("종목 DB 없음 — 매칭 스킵")

        # ── Step 6: 분석 결과 저장 ────────────────────────
        if not dry_run and results:
            log.step(f"{len(results)}건 분석 결과 저장 중...")
            saved = self._store.save_analyses(results)
            summary["saved_analyses"] = saved
            log.success(f"{saved}건 저장")
        elif dry_run:
            log.step("[dry-run] 분석 결과 저장 스킵")

        # ── Step 7: AI 판단 추적 로그 저장 ───────────────
        traces = self._claude.flush_traces()
        if traces and not dry_run:
            log.step(f"AI 판단 추적 로그 {len(traces)}건 저장 중...")
            try:
                self._store.save_traces(traces)
                log.success(f"{len(traces)}건 저장")
            except Exception as e:
                log.warn(f"추적 로그 저장 실패 (파이프라인은 계속): {e}")
        elif dry_run and traces:
            log.step(f"[dry-run] 추적 로그 저장 스킵 ({len(traces)}건 수집됨)")

        return summary
