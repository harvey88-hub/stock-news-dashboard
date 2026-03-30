"""
stores/supabase_store.py
========================
Supabase PostgreSQL 저장소 구현체.
기존 코드 곳곳에 흩어져 있던 supabase.table(...) 호출을 한 곳에 모읍니다.
"""

from __future__ import annotations
from datetime import datetime, timezone, timedelta

from core.config import AppConfig
from core.interfaces import Article, AnalysisResult, StockMatch, ListedStock
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
            "hour":          r.hour,
            "sector":        r.sector,
            "headline":      r.headline,
            "ai_summary":    r.ai_summary,
            "stocks":        r.stocks_as_dicts(),
            "article_count": r.article_count,
            "source_list":   sources,
        }

    @staticmethod
    def _row_to_analysis(r: dict) -> AnalysisResult:
        stocks_raw = r.get("stocks") or []
        stocks = [
            StockMatch(name=s.get("name", ""), reason=s.get("reason", ""))
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
