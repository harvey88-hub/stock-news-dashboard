"""
stores/supabase_store.py
========================
Supabase PostgreSQL 저장소 구현체.
기존 코드 곳곳에 흩어져 있던 supabase.table(...) 호출을 한 곳에 모읍니다.
"""

from __future__ import annotations
from datetime import datetime, timezone, timedelta

from core.config import AppConfig
from core.interfaces import Article, AnalysisResult, StockMatch, ListedStock, AnalysisTrace, DailySummary
from core.logging import get_logger
from core.errors import StoreError, ConfigError

KST = timezone(timedelta(hours=9))


class SupabaseStore:
    """
    Supabase를 백엔드로 사용하는 Store 구현체.

    Store 프로토콜 구현::

        store = SupabaseStore(config)
        store.save_articles(articles)
        store.get_analyses(hours_back=24)
    """

    name = "supabase"

    def __init__(self, config: AppConfig):
        if not config.supabase_url or not config.supabase_key:
            raise ConfigError("SUPABASE_URL, SUPABASE_KEY 환경 변수가 필요합니다.")

        from supabase import create_client
        self._client = create_client(config.supabase_url, config.supabase_key)
        self._tables = config.store.supabase_tables
        self._batch  = config.store.supabase_batch_size
        self._log    = get_logger("supabase")

    # ──────────────────────────────────────
    # 쓰기
    # ──────────────────────────────────────

    def save_articles(self, articles: list[Article]) -> int:
        """기사를 news_articles 테이블에 upsert합니다. 저장된 건수를 반환합니다."""
        if not articles:
            return 0

        table = self._tables["articles"]
        rows  = [self._article_to_row(a) for a in articles]
        rows  = self._dedup_by_key(rows, "link")

        try:
            result = self._client.table(table).upsert(rows, on_conflict="link").execute()
            count  = len(result.data) if result.data else 0
            self._log.info(f"articles 저장: {count}건 (입력 {len(rows)}건)")
            return count
        except Exception as e:
            raise StoreError("supabase", f"articles 저장 실패: {e}") from e

    def save_analyses(self, results: list[AnalysisResult]) -> int:
        """분석 결과를 timeline_issues 테이블에 upsert합니다."""
        if not results:
            return 0

        table = self._tables["analyses"]
        rows  = [self._analysis_to_row(r) for r in results]

        try:
            result = self._client.table(table).upsert(rows, on_conflict="hour").execute()
            count  = len(result.data) if result.data else 0
            self._log.info(f"analyses 저장: {count}건")
            return count
        except Exception as e:
            raise StoreError("supabase", f"analyses 저장 실패: {e}") from e

    def save_stocks(self, stocks: list[ListedStock]) -> int:
        """상장 종목을 listed_stocks 테이블에 배치 upsert합니다."""
        if not stocks:
            return 0

        table = self._tables["stocks"]
        rows  = [
            {
                "stock_code": s.stock_code,
                "stock_name": s.stock_name,
                "market":     s.market,
                "isin_code":  s.isin_code,
                "corp_name":  s.corp_name,
                "updated_at": datetime.now().isoformat(),
            }
            for s in stocks
        ]

        total = 0
        for i in range(0, len(rows), self._batch):
            batch = rows[i:i + self._batch]
            try:
                result = self._client.table(table).upsert(
                    batch, on_conflict="stock_code"
                ).execute()
                total += len(result.data) if result.data else 0
                self._log.info(f"stocks 저장: {i + len(batch)}/{len(rows)}")
            except Exception as e:
                raise StoreError("supabase", f"stocks 배치 저장 실패: {e}") from e

        return total

    # ──────────────────────────────────────
    # 읽기
    # ──────────────────────────────────────

    def get_articles(self, hours_back: int = 24) -> list[Article]:
        """최근 N시간 이내 기사를 반환합니다."""
        cutoff = (datetime.now(KST) - timedelta(hours=hours_back)).strftime("%Y-%m-%d %H:%M")
        table  = self._tables["articles"]
        try:
            result = (
                self._client.table(table)
                .select("id, source, title, pubdate_kst, collected_at, link, summary")
                .gte("collected_at", cutoff)
                .order("collected_at", desc=True)
                .limit(1000)
                .execute()
            )
            return [self._row_to_article(r) for r in (result.data or [])]
        except Exception as e:
            raise StoreError("supabase", f"articles 조회 실패: {e}") from e

    def get_analyses(self, hours_back: int = 24) -> list[AnalysisResult]:
        """최근 N시간 이내 분석 결과를 반환합니다."""
        cutoff = (datetime.now(KST) - timedelta(hours=hours_back)).strftime("%Y-%m-%d %H:%M")
        table  = self._tables["analyses"]
        try:
            result = (
                self._client.table(table)
                .select("*")
                .gte("hour", cutoff)
                .order("hour", desc=True)
                .execute()
            )
            return [self._row_to_analysis(r) for r in (result.data or [])]
        except Exception as e:
            raise StoreError("supabase", f"analyses 조회 실패: {e}") from e

    def get_listed_stocks(self) -> dict[str, str]:
        """{종목명: 종목코드} 딕셔너리를 반환합니다."""
        table = self._tables["stocks"]
        try:
            result = self._client.table(table).select("stock_code, stock_name").execute()
            return {r["stock_name"]: r["stock_code"] for r in (result.data or [])}
        except Exception as e:
            raise StoreError("supabase", f"listed_stocks 조회 실패: {e}") from e

    def get_analyzed_hours(self, hours_back: int = 24) -> set[str]:
        """이미 분석된 시간대 키 집합을 반환합니다."""
        cutoff = (datetime.now(KST) - timedelta(hours=hours_back)).strftime("%Y-%m-%d %H:%M")
        table  = self._tables["analyses"]
        try:
            result = (
                self._client.table(table)
                .select("hour")
                .gte("hour", cutoff)
                .execute()
            )
            return {r["hour"] for r in (result.data or [])}
        except Exception as e:
            raise StoreError("supabase", f"analyzed_hours 조회 실패: {e}") from e

    def save_traces(self, traces: list[AnalysisTrace]) -> int:
        """AI 분석 과정 추적 로그를 analysis_traces 테이블에 저장합니다.

        Supabase에서 아래 SQL로 테이블을 먼저 생성해야 합니다:

            CREATE TABLE analysis_traces (
                id                       BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
                hour                     TEXT NOT NULL,
                created_at               TEXT,
                input_article_count      INT DEFAULT 0,
                input_articles           JSONB,
                step1_issue              TEXT,
                step1_filtered_count     INT DEFAULT 0,
                -- Step 0
                step0_removed_count      INT DEFAULT 0,
                step0_removal_reasons    JSONB,
                -- Step 1b
                similarity_checked       BOOLEAN DEFAULT FALSE,
                compared_headlines       JSONB,
                is_duplicate             BOOLEAN DEFAULT FALSE,
                similar_to               TEXT,
                similarity_reason        TEXT,
                retry_count              INT DEFAULT 0,
                issue_after_dedup        TEXT,
                is_evolution             BOOLEAN DEFAULT FALSE,
                evolution_of             TEXT,
                evolution_type           TEXT,
                -- Step 1c
                review_approved          BOOLEAN DEFAULT TRUE,
                review_feedback          TEXT,
                issue_after_review       TEXT,
                -- Step 2
                final_headline           TEXT,
                final_sector             TEXT,
                -- Step 2b
                factcheck_passed         BOOLEAN DEFAULT TRUE,
                factcheck_corrections    JSONB,
                headline_before_factcheck TEXT,
                -- Step 2c
                summary_quality_passed   BOOLEAN DEFAULT TRUE,
                summary_regenerated      BOOLEAN DEFAULT FALSE,
                summary_quality_feedback TEXT,
                -- Scoring
                impact_score             INT DEFAULT 0,
                impact_score_reason      TEXT,
                -- 스킵
                skipped                  BOOLEAN DEFAULT FALSE,
                no_issue_reason          TEXT
            );

            -- 기존 테이블에 컬럼 추가 (이미 테이블이 있는 경우):
            -- ALTER TABLE analysis_traces ADD COLUMN IF NOT EXISTS step0_removed_count INT DEFAULT 0;
            -- ALTER TABLE analysis_traces ADD COLUMN IF NOT EXISTS step0_removal_reasons JSONB;
            -- ALTER TABLE analysis_traces ADD COLUMN IF NOT EXISTS is_evolution BOOLEAN DEFAULT FALSE;
            -- ALTER TABLE analysis_traces ADD COLUMN IF NOT EXISTS evolution_of TEXT;
            -- ALTER TABLE analysis_traces ADD COLUMN IF NOT EXISTS evolution_type TEXT;
            -- ALTER TABLE analysis_traces ADD COLUMN IF NOT EXISTS factcheck_passed BOOLEAN DEFAULT TRUE;
            -- ALTER TABLE analysis_traces ADD COLUMN IF NOT EXISTS factcheck_corrections JSONB;
            -- ALTER TABLE analysis_traces ADD COLUMN IF NOT EXISTS headline_before_factcheck TEXT;
            -- ALTER TABLE analysis_traces ADD COLUMN IF NOT EXISTS summary_quality_passed BOOLEAN DEFAULT TRUE;
            -- ALTER TABLE analysis_traces ADD COLUMN IF NOT EXISTS summary_regenerated BOOLEAN DEFAULT FALSE;
            -- ALTER TABLE analysis_traces ADD COLUMN IF NOT EXISTS summary_quality_feedback TEXT;
            -- ALTER TABLE analysis_traces ADD COLUMN IF NOT EXISTS impact_score INT DEFAULT 0;
            -- ALTER TABLE analysis_traces ADD COLUMN IF NOT EXISTS impact_score_reason TEXT;
            -- ALTER TABLE analysis_traces ADD COLUMN IF NOT EXISTS skipped BOOLEAN DEFAULT FALSE;
            -- ALTER TABLE analysis_traces ADD COLUMN IF NOT EXISTS no_issue_reason TEXT;
        """
        if not traces:
            return 0
        rows = [
            {
                "hour":                       t.hour,
                "created_at":                 t.created_at,
                "input_article_count":        t.input_article_count,
                "input_articles":             t.input_articles,
                "step1_issue":                t.step1_issue,
                "step1_filtered_count":       t.step1_filtered_count,
                "step0_removed_count":        t.step0_removed_count,
                "step0_removal_reasons":      t.step0_removal_reasons,
                "similarity_checked":         t.similarity_checked,
                "compared_headlines":         t.compared_headlines,
                "is_duplicate":               t.is_duplicate,
                "similar_to":                 t.similar_to,
                "similarity_reason":          t.similarity_reason,
                "retry_count":                t.retry_count,
                "issue_after_dedup":          t.issue_after_dedup,
                "is_evolution":               t.is_evolution,
                "evolution_of":               t.evolution_of,
                "evolution_type":             t.evolution_type,
                "review_approved":            t.review_approved,
                "review_feedback":            t.review_feedback,
                "issue_after_review":         t.issue_after_review,
                "final_headline":             t.final_headline,
                "final_sector":               t.final_sector,
                "factcheck_passed":           t.factcheck_passed,
                "factcheck_corrections":      t.factcheck_corrections,
                "headline_before_factcheck":  t.headline_before_factcheck,
                "summary_quality_passed":     t.summary_quality_passed,
                "summary_regenerated":        t.summary_regenerated,
                "summary_quality_feedback":   t.summary_quality_feedback,
                "impact_score":               t.impact_score,
                "impact_score_reason":        t.impact_score_reason,
                "skipped":                    t.skipped,
                "no_issue_reason":            t.no_issue_reason,
            }
            for t in traces
        ]
        try:
            result = self._client.table("analysis_traces").insert(rows).execute()
            count  = len(result.data) if result.data else 0
            self._log.info(f"traces 저장: {count}건")
            return count
        except Exception as e:
            raise StoreError("supabase", f"traces 저장 실패: {e}") from e

    def get_traces(self, hours_back: int = 24) -> list[AnalysisTrace]:
        """최근 N시간 이내 분석 추적 로그를 반환합니다."""
        cutoff = (datetime.now(KST) - timedelta(hours=hours_back)).strftime("%Y-%m-%d %H:%M")
        try:
            result = (
                self._client.table("analysis_traces")
                .select("*")
                .gte("hour", cutoff)
                .order("created_at", desc=True)
                .execute()
            )
            return [
                AnalysisTrace(
                    hour=r.get("hour", ""),
                    created_at=r.get("created_at", ""),
                    input_article_count=r.get("input_article_count", 0),
                    input_articles=r.get("input_articles") or [],
                    step1_issue=r.get("step1_issue", ""),
                    step1_filtered_count=r.get("step1_filtered_count", 0),
                    step0_removed_count=r.get("step0_removed_count", 0) or 0,
                    step0_removal_reasons=r.get("step0_removal_reasons") or [],
                    similarity_checked=bool(r.get("similarity_checked")),
                    compared_headlines=r.get("compared_headlines") or [],
                    is_duplicate=bool(r.get("is_duplicate")),
                    similar_to=r.get("similar_to", ""),
                    similarity_reason=r.get("similarity_reason", ""),
                    retry_count=r.get("retry_count", 0),
                    issue_after_dedup=r.get("issue_after_dedup", ""),
                    is_evolution=bool(r.get("is_evolution", False)),
                    evolution_of=r.get("evolution_of", "") or "",
                    evolution_type=r.get("evolution_type", "") or "",
                    review_approved=bool(r.get("review_approved", True)),
                    review_feedback=r.get("review_feedback", ""),
                    issue_after_review=r.get("issue_after_review", ""),
                    final_headline=r.get("final_headline", ""),
                    final_sector=r.get("final_sector", ""),
                    factcheck_passed=bool(r.get("factcheck_passed", True)),
                    factcheck_corrections=r.get("factcheck_corrections") or [],
                    headline_before_factcheck=r.get("headline_before_factcheck", "") or "",
                    summary_quality_passed=bool(r.get("summary_quality_passed", True)),
                    summary_regenerated=bool(r.get("summary_regenerated", False)),
                    summary_quality_feedback=r.get("summary_quality_feedback", "") or "",
                    impact_score=r.get("impact_score", 0) or 0,
                    impact_score_reason=r.get("impact_score_reason", "") or "",
                    skipped=bool(r.get("skipped", False)),
                    no_issue_reason=r.get("no_issue_reason", ""),
                )
                for r in (result.data or [])
            ]
        except Exception as e:
            raise StoreError("supabase", f"traces 조회 실패: {e}") from e

    def save_daily_summary(self, summary: DailySummary) -> bool:
        """일일 브리핑 요약을 daily_summaries 테이블에 upsert합니다.

        Supabase에서 아래 SQL로 테이블을 먼저 생성해야 합니다:

            CREATE TABLE daily_summaries (
                date         TEXT PRIMARY KEY,
                created_at   TEXT,
                top_issues   JSONB,
                market_flow  TEXT,
                hot_sectors  JSONB,
                hot_stocks   JSONB
            );
        """
        row = {
            "date":        summary.date,
            "created_at":  summary.created_at,
            "top_issues":  summary.top_issues,
            "market_flow": summary.market_flow,
            "hot_sectors": summary.hot_sectors,
            "hot_stocks":  summary.hot_stocks,
        }
        try:
            self._client.table("daily_summaries").upsert(row, on_conflict="date").execute()
            self._log.info(f"daily_summary 저장: {summary.date}")
            return True
        except Exception as e:
            raise StoreError("supabase", f"daily_summary 저장 실패: {e}") from e

    def get_daily_summary(self, date: str) -> DailySummary | None:
        """특정 날짜(YYYY-MM-DD)의 일일 브리핑 요약을 반환합니다. 없으면 None."""
        try:
            result = (
                self._client.table("daily_summaries")
                .select("*")
                .eq("date", date)
                .limit(1)
                .execute()
            )
            rows = result.data or []
            if not rows:
                return None
            r = rows[0]
            return DailySummary(
                date=r.get("date", date),
                created_at=r.get("created_at", ""),
                top_issues=r.get("top_issues") or [],
                market_flow=r.get("market_flow", "") or "",
                hot_sectors=r.get("hot_sectors") or [],
                hot_stocks=r.get("hot_stocks") or [],
            )
        except Exception as e:
            raise StoreError("supabase", f"daily_summary 조회 실패: {e}") from e

    # ──────────────────────────────────────
    # 변환 헬퍼
    # ──────────────────────────────────────

    @staticmethod
    def _article_to_row(a: Article) -> dict:
        return {
            "collected_at": a.collected_at,
            "source":       a.source,
            "title":        a.title,
            "pubdate_raw":  a.pubdate_raw,
            "pubdate_kst":  a.published_at,
            "link":         a.link,
            "summary":      a.summary,
        }

    @staticmethod
    def _row_to_article(r: dict) -> Article:
        return Article(
            source=r.get("source", ""),
            title=r.get("title", ""),
            link=r.get("link", ""),
            published_at=r.get("pubdate_kst", ""),
            collected_at=r.get("collected_at", ""),
            summary=r.get("summary", "") or "",
            pubdate_raw=r.get("pubdate_raw", "") or "",
        )

    @staticmethod
    def _analysis_to_row(r: AnalysisResult) -> dict:
        sources = r.source_list
        return {
            "hour":           r.hour,
            "sector":         r.sector,
            "headline":       r.headline,
            "ai_summary":     r.ai_summary,
            "stocks":         r.stocks_as_dicts(),
            "article_count":  r.article_count,
            "source_list":    sources,
            "impact_score":   r.impact_score,
            "is_evolution":   r.is_evolution,
            "evolution_type": r.evolution_type,
        }

    @staticmethod
    def _row_to_analysis(r: dict) -> AnalysisResult:
        stocks_raw = r.get("stocks") or []
        stocks = [
            StockMatch(name=s.get("name", ""), reason=s.get("reason", ""), source=s.get("source", "article"))
            for s in stocks_raw
            if isinstance(s, dict)
        ]
        return AnalysisResult(
            hour=r.get("hour", ""),
            sector=r.get("sector", ""),
            headline=r.get("headline", ""),
            ai_summary=r.get("ai_summary", ""),
            related_stocks=stocks,
            article_count=r.get("article_count", 0),
            source_list=r.get("source_list", ""),
            impact_score=r.get("impact_score", 0) or 0,
            is_evolution=bool(r.get("is_evolution", False)),
            evolution_type=r.get("evolution_type", "") or "",
        )

    @staticmethod
    def _dedup_by_key(rows: list[dict], key: str) -> list[dict]:
        seen:   set    = set()
        result: list   = []
        for row in rows:
            val = row.get(key, "")
            if val and val not in seen:
                seen.add(val)
                result.append(row)
            elif not val:
                result.append(row)
        return result
