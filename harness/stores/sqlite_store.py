"""
stores/sqlite_store.py
=======================
SQLite 저장소 구현체 (로컬 개발 / 테스트용).
Supabase 없이도 전체 파이프라인을 로컬에서 실행할 수 있습니다.
"""

from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

from core.config import AppConfig
from core.interfaces import Article, AnalysisResult, StockMatch, ListedStock, AnalysisTrace, DailySummary
from core.logging import get_logger

KST = timezone(timedelta(hours=9))


class SQLiteStore:
    """
    SQLite를 백엔드로 사용하는 Store 구현체.
    db 파일은 config.store.sqlite_path에 지정된 경로에 생성됩니다.
    """

    name = "sqlite"

    def __init__(self, config: AppConfig):
        self._path = Path(config.store.sqlite_path)
        self._log  = get_logger("sqlite")
        self._init_db()

    # ──────────────────────────────────────
    # 초기화
    # ──────────────────────────────────────

    def _init_db(self):
        """테이블이 없으면 생성하고, 기존 테이블에 누락된 컬럼을 추가합니다."""
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS news_articles (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    source       TEXT,
                    title        TEXT,
                    link         TEXT UNIQUE,
                    pubdate_raw  TEXT,
                    pubdate_kst  TEXT,
                    collected_at TEXT,
                    summary      TEXT,
                    created_at   TEXT DEFAULT (datetime('now'))
                );
                CREATE TABLE IF NOT EXISTS timeline_issues (
                    hour           TEXT PRIMARY KEY,
                    sector         TEXT,
                    headline       TEXT,
                    ai_summary     TEXT,
                    stocks         TEXT,
                    article_count  INTEGER,
                    source_list    TEXT,
                    impact_score   INTEGER DEFAULT 0,
                    is_evolution   INTEGER DEFAULT 0,
                    evolution_type TEXT DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS listed_stocks (
                    stock_code TEXT PRIMARY KEY,
                    stock_name TEXT,
                    market     TEXT,
                    isin_code  TEXT,
                    corp_name  TEXT,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS analysis_traces (
                    id                        INTEGER PRIMARY KEY AUTOINCREMENT,
                    hour                      TEXT NOT NULL,
                    created_at                TEXT,
                    input_article_count       INTEGER DEFAULT 0,
                    input_articles            TEXT,   -- JSON [{source, title}]
                    step1_issue               TEXT,
                    step1_filtered_count      INTEGER DEFAULT 0,
                    -- Step 0
                    step0_removed_count       INTEGER DEFAULT 0,
                    step0_removal_reasons     TEXT,   -- JSON [str]
                    -- Step 1b
                    similarity_checked        INTEGER DEFAULT 0,
                    compared_headlines        TEXT,   -- JSON [str]
                    is_duplicate              INTEGER DEFAULT 0,
                    similar_to                TEXT,
                    similarity_reason         TEXT,
                    retry_count               INTEGER DEFAULT 0,
                    issue_after_dedup         TEXT,
                    is_evolution              INTEGER DEFAULT 0,
                    evolution_of              TEXT,
                    evolution_type            TEXT,
                    -- Step 1c
                    review_approved           INTEGER DEFAULT 1,
                    review_feedback           TEXT,
                    issue_after_review        TEXT,
                    -- Step 2
                    final_headline            TEXT,
                    final_sector              TEXT,
                    -- Step 2b
                    factcheck_passed          INTEGER DEFAULT 1,
                    factcheck_corrections     TEXT,   -- JSON [str]
                    headline_before_factcheck TEXT,
                    -- Step 2c
                    summary_quality_passed    INTEGER DEFAULT 1,
                    summary_regenerated       INTEGER DEFAULT 0,
                    summary_quality_feedback  TEXT,
                    -- Scoring
                    impact_score              INTEGER DEFAULT 0,
                    impact_score_reason       TEXT,
                    -- 스킵
                    skipped                   INTEGER DEFAULT 0,
                    no_issue_reason           TEXT
                );
                CREATE TABLE IF NOT EXISTS daily_summaries (
                    date         TEXT PRIMARY KEY,
                    created_at   TEXT,
                    top_issues   TEXT,   -- JSON
                    market_flow  TEXT,
                    hot_sectors  TEXT,   -- JSON [str]
                    hot_stocks   TEXT    -- JSON [{name, code, mention_count}]
                );
            """)

            # 기존 DB 호환: timeline_issues 새 컬럼 추가
            for col, definition in [
                ("impact_score",   "INTEGER DEFAULT 0"),
                ("is_evolution",   "INTEGER DEFAULT 0"),
                ("evolution_type", "TEXT DEFAULT ''"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE timeline_issues ADD COLUMN {col} {definition}")
                except Exception:
                    pass  # 이미 존재하면 무시

            # 기존 DB 호환: analysis_traces 새 컬럼 추가
            for col, definition in [
                ("step0_removed_count",       "INTEGER DEFAULT 0"),
                ("step0_removal_reasons",     "TEXT"),
                ("is_evolution",              "INTEGER DEFAULT 0"),
                ("evolution_of",              "TEXT"),
                ("evolution_type",            "TEXT"),
                ("factcheck_passed",          "INTEGER DEFAULT 1"),
                ("factcheck_corrections",     "TEXT"),
                ("headline_before_factcheck", "TEXT"),
                ("summary_quality_passed",    "INTEGER DEFAULT 1"),
                ("summary_regenerated",       "INTEGER DEFAULT 0"),
                ("summary_quality_feedback",  "TEXT"),
                ("impact_score",              "INTEGER DEFAULT 0"),
                ("impact_score_reason",       "TEXT"),
                ("skipped",                   "INTEGER DEFAULT 0"),
                ("no_issue_reason",           "TEXT"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE analysis_traces ADD COLUMN {col} {definition}")
                except Exception:
                    pass  # 이미 존재하면 무시

        self._log.info(f"SQLite DB 초기화 완료: {self._path}")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    # ──────────────────────────────────────
    # 쓰기
    # ──────────────────────────────────────

    def save_articles(self, articles: list[Article]) -> int:
        if not articles:
            return 0
        sql = """
            INSERT OR REPLACE INTO news_articles
                (source, title, link, pubdate_raw, pubdate_kst, collected_at, summary)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        rows = [
            (a.source, a.title, a.link, a.pubdate_raw, a.published_at, a.collected_at, a.summary)
            for a in articles
        ]
        with self._conn() as conn:
            conn.executemany(sql, rows)
        self._log.info(f"articles 저장: {len(rows)}건")
        return len(rows)

    def save_analyses(self, results: list[AnalysisResult]) -> int:
        if not results:
            return 0
        sql = """
            INSERT OR REPLACE INTO timeline_issues
                (hour, sector, headline, ai_summary, stocks, article_count, source_list,
                 impact_score, is_evolution, evolution_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        rows = [
            (
                r.hour, r.sector, r.headline, r.ai_summary,
                json.dumps(r.stocks_as_dicts(), ensure_ascii=False),
                r.article_count, r.source_list,
                r.impact_score,
                int(r.is_evolution),
                r.evolution_type,
            )
            for r in results
        ]
        with self._conn() as conn:
            conn.executemany(sql, rows)
        self._log.info(f"analyses 저장: {len(rows)}건")
        return len(rows)

    def save_stocks(self, stocks: list[ListedStock]) -> int:
        if not stocks:
            return 0
        sql = """
            INSERT OR REPLACE INTO listed_stocks
                (stock_code, stock_name, market, isin_code, corp_name, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        rows = [
            (s.stock_code, s.stock_name, s.market, s.isin_code, s.corp_name,
             datetime.now().isoformat())
            for s in stocks
        ]
        with self._conn() as conn:
            conn.executemany(sql, rows)
        self._log.info(f"stocks 저장: {len(rows)}건")
        return len(rows)

    # ──────────────────────────────────────
    # 읽기
    # ──────────────────────────────────────

    def get_articles(self, hours_back: int = 24) -> list[Article]:
        cutoff = (datetime.now(KST) - timedelta(hours=hours_back)).strftime("%Y-%m-%d %H:%M")
        sql    = "SELECT * FROM news_articles WHERE collected_at >= ? ORDER BY collected_at DESC LIMIT 1000"
        with self._conn() as conn:
            rows = conn.execute(sql, (cutoff,)).fetchall()
        return [
            Article(
                source=r["source"] or "",
                title=r["title"] or "",
                link=r["link"] or "",
                published_at=r["pubdate_kst"] or "",
                collected_at=r["collected_at"] or "",
                summary=r["summary"] or "",
                pubdate_raw=r["pubdate_raw"] or "",
            )
            for r in rows
        ]

    def get_analyses(self, hours_back: int = 24) -> list[AnalysisResult]:
        cutoff = (datetime.now(KST) - timedelta(hours=hours_back)).strftime("%Y-%m-%d %H:%M")
        sql    = "SELECT * FROM timeline_issues WHERE hour >= ? ORDER BY hour DESC"
        with self._conn() as conn:
            rows = conn.execute(sql, (cutoff,)).fetchall()
        results = []
        for r in rows:
            stocks_raw = json.loads(r["stocks"] or "[]")
            stocks = [StockMatch(name=s.get("name", ""), reason=s.get("reason", ""), source=s.get("source", "article"))
                      for s in stocks_raw if isinstance(s, dict)]
            results.append(AnalysisResult(
                hour=r["hour"],
                sector=r["sector"] or "",
                headline=r["headline"] or "",
                ai_summary=r["ai_summary"] or "",
                related_stocks=stocks,
                article_count=r["article_count"] or 0,
                source_list=r["source_list"] or "",
                impact_score=r["impact_score"] if r["impact_score"] is not None else 0,
                is_evolution=bool(r["is_evolution"]) if r["is_evolution"] is not None else False,
                evolution_type=r["evolution_type"] or "",
            ))
        return results

    def get_listed_stocks(self) -> dict[str, str]:
        sql = "SELECT stock_code, stock_name FROM listed_stocks"
        with self._conn() as conn:
            rows = conn.execute(sql).fetchall()
        return {r["stock_name"]: r["stock_code"] for r in rows}

    def get_analyzed_hours(self, hours_back: int = 24) -> set[str]:
        cutoff = (datetime.now(KST) - timedelta(hours=hours_back)).strftime("%Y-%m-%d %H:%M")
        sql    = "SELECT hour FROM timeline_issues WHERE hour >= ?"
        with self._conn() as conn:
            rows = conn.execute(sql, (cutoff,)).fetchall()
        return {r["hour"] for r in rows}

    def save_traces(self, traces: list[AnalysisTrace]) -> int:
        if not traces:
            return 0
        sql = """
            INSERT INTO analysis_traces (
                hour, created_at,
                input_article_count, input_articles,
                step1_issue, step1_filtered_count,
                step0_removed_count, step0_removal_reasons,
                similarity_checked, compared_headlines,
                is_duplicate, similar_to, similarity_reason,
                retry_count, issue_after_dedup,
                is_evolution, evolution_of, evolution_type,
                review_approved, review_feedback, issue_after_review,
                final_headline, final_sector,
                factcheck_passed, factcheck_corrections, headline_before_factcheck,
                summary_quality_passed, summary_regenerated, summary_quality_feedback,
                impact_score, impact_score_reason,
                skipped, no_issue_reason
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
        """
        rows = [
            (
                t.hour, t.created_at,
                t.input_article_count,
                json.dumps(t.input_articles, ensure_ascii=False),
                t.step1_issue, t.step1_filtered_count,
                t.step0_removed_count,
                json.dumps(t.step0_removal_reasons, ensure_ascii=False),
                int(t.similarity_checked),
                json.dumps(t.compared_headlines, ensure_ascii=False),
                int(t.is_duplicate), t.similar_to, t.similarity_reason,
                t.retry_count, t.issue_after_dedup,
                int(t.is_evolution), t.evolution_of, t.evolution_type,
                int(t.review_approved), t.review_feedback, t.issue_after_review,
                t.final_headline, t.final_sector,
                int(t.factcheck_passed),
                json.dumps(t.factcheck_corrections, ensure_ascii=False),
                t.headline_before_factcheck,
                int(t.summary_quality_passed),
                int(t.summary_regenerated),
                t.summary_quality_feedback,
                t.impact_score, t.impact_score_reason,
                int(t.skipped), t.no_issue_reason,
            )
            for t in traces
        ]
        with self._conn() as conn:
            conn.executemany(sql, rows)
        self._log.info(f"traces 저장: {len(rows)}건")
        return len(rows)

    def get_traces(self, hours_back: int = 24) -> list[AnalysisTrace]:
        cutoff = (datetime.now(KST) - timedelta(hours=hours_back)).strftime("%Y-%m-%d %H:%M")
        sql    = "SELECT * FROM analysis_traces WHERE hour >= ? ORDER BY created_at DESC"
        with self._conn() as conn:
            rows = conn.execute(sql, (cutoff,)).fetchall()

        def _col(r, col, default=None):
            """Row에서 컬럼을 안전하게 읽습니다 (구버전 DB 호환)."""
            try:
                return r[col]
            except (IndexError, KeyError):
                return default

        return [
            AnalysisTrace(
                hour=r["hour"],
                created_at=r["created_at"] or "",
                input_article_count=r["input_article_count"] or 0,
                input_articles=json.loads(r["input_articles"] or "[]"),
                step1_issue=r["step1_issue"] or "",
                step1_filtered_count=r["step1_filtered_count"] or 0,
                step0_removed_count=_col(r, "step0_removed_count", 0) or 0,
                step0_removal_reasons=json.loads(_col(r, "step0_removal_reasons") or "[]"),
                similarity_checked=bool(r["similarity_checked"]),
                compared_headlines=json.loads(r["compared_headlines"] or "[]"),
                is_duplicate=bool(r["is_duplicate"]),
                similar_to=r["similar_to"] or "",
                similarity_reason=r["similarity_reason"] or "",
                retry_count=r["retry_count"] or 0,
                issue_after_dedup=r["issue_after_dedup"] or "",
                is_evolution=bool(_col(r, "is_evolution", 0)),
                evolution_of=_col(r, "evolution_of") or "",
                evolution_type=_col(r, "evolution_type") or "",
                review_approved=bool(r["review_approved"]),
                review_feedback=r["review_feedback"] or "",
                issue_after_review=r["issue_after_review"] or "",
                final_headline=r["final_headline"] or "",
                final_sector=r["final_sector"] or "",
                factcheck_passed=bool(_col(r, "factcheck_passed", 1)),
                factcheck_corrections=json.loads(_col(r, "factcheck_corrections") or "[]"),
                headline_before_factcheck=_col(r, "headline_before_factcheck") or "",
                summary_quality_passed=bool(_col(r, "summary_quality_passed", 1)),
                summary_regenerated=bool(_col(r, "summary_regenerated", 0)),
                summary_quality_feedback=_col(r, "summary_quality_feedback") or "",
                impact_score=_col(r, "impact_score", 0) or 0,
                impact_score_reason=_col(r, "impact_score_reason") or "",
                skipped=bool(_col(r, "skipped", 0)),
                no_issue_reason=_col(r, "no_issue_reason") or "",
            )
            for r in rows
        ]

    def save_daily_summary(self, summary: DailySummary) -> bool:
        """일일 브리핑 요약을 daily_summaries 테이블에 upsert합니다."""
        sql = """
            INSERT OR REPLACE INTO daily_summaries
                (date, created_at, top_issues, market_flow, hot_sectors, hot_stocks)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        row = (
            summary.date,
            summary.created_at,
            json.dumps(summary.top_issues, ensure_ascii=False),
            summary.market_flow,
            json.dumps(summary.hot_sectors, ensure_ascii=False),
            json.dumps(summary.hot_stocks, ensure_ascii=False),
        )
        with self._conn() as conn:
            conn.execute(sql, row)
        self._log.info(f"daily_summary 저장: {summary.date}")
        return True

    def get_daily_summary(self, date: str) -> DailySummary | None:
        """특정 날짜(YYYY-MM-DD)의 일일 브리핑 요약을 반환합니다. 없으면 None."""
        sql = "SELECT * FROM daily_summaries WHERE date = ? LIMIT 1"
        with self._conn() as conn:
            row = conn.execute(sql, (date,)).fetchone()
        if not row:
            return None
        return DailySummary(
            date=row["date"],
            created_at=row["created_at"] or "",
            top_issues=json.loads(row["top_issues"] or "[]"),
            market_flow=row["market_flow"] or "",
            hot_sectors=json.loads(row["hot_sectors"] or "[]"),
            hot_stocks=json.loads(row["hot_stocks"] or "[]"),
        )
