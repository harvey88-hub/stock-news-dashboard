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
from core.interfaces import Article, AnalysisResult, StockMatch, ListedStock, AnalysisTrace
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
        """테이블이 없으면 생성합니다."""
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
                    hour          TEXT PRIMARY KEY,
                    sector        TEXT,
                    headline      TEXT,
                    ai_summary    TEXT,
                    stocks        TEXT,
                    article_count INTEGER,
                    source_list   TEXT
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
                    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                    hour                 TEXT NOT NULL,
                    created_at           TEXT,
                    input_article_count  INTEGER DEFAULT 0,
                    input_articles       TEXT,   -- JSON [{source, title}]
                    step1_issue          TEXT,
                    step1_filtered_count INTEGER DEFAULT 0,
                    similarity_checked   INTEGER DEFAULT 0,
                    compared_headlines   TEXT,   -- JSON [str]
                    is_duplicate         INTEGER DEFAULT 0,
                    similar_to           TEXT,
                    similarity_reason    TEXT,
                    retry_count          INTEGER DEFAULT 0,
                    issue_after_dedup    TEXT,
                    review_approved      INTEGER DEFAULT 1,
                    review_feedback      TEXT,
                    issue_after_review   TEXT,
                    final_headline       TEXT,
                    final_sector         TEXT
                );
            """)
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
                (hour, sector, headline, ai_summary, stocks, article_count, source_list)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        rows = [
            (
                r.hour, r.sector, r.headline, r.ai_summary,
                json.dumps(r.stocks_as_dicts(), ensure_ascii=False),
                r.article_count, r.source_list,
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
                similarity_checked, compared_headlines,
                is_duplicate, similar_to, similarity_reason,
                retry_count, issue_after_dedup,
                review_approved, review_feedback, issue_after_review,
                final_headline, final_sector
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        rows = [
            (
                t.hour, t.created_at,
                t.input_article_count,
                json.dumps(t.input_articles, ensure_ascii=False),
                t.step1_issue, t.step1_filtered_count,
                int(t.similarity_checked),
                json.dumps(t.compared_headlines, ensure_ascii=False),
                int(t.is_duplicate), t.similar_to, t.similarity_reason,
                t.retry_count, t.issue_after_dedup,
                int(t.review_approved), t.review_feedback, t.issue_after_review,
                t.final_headline, t.final_sector,
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
        return [
            AnalysisTrace(
                hour=r["hour"],
                created_at=r["created_at"] or "",
                input_article_count=r["input_article_count"] or 0,
                input_articles=json.loads(r["input_articles"] or "[]"),
                step1_issue=r["step1_issue"] or "",
                step1_filtered_count=r["step1_filtered_count"] or 0,
                similarity_checked=bool(r["similarity_checked"]),
                compared_headlines=json.loads(r["compared_headlines"] or "[]"),
                is_duplicate=bool(r["is_duplicate"]),
                similar_to=r["similar_to"] or "",
                similarity_reason=r["similarity_reason"] or "",
                retry_count=r["retry_count"] or 0,
                issue_after_dedup=r["issue_after_dedup"] or "",
                review_approved=bool(r["review_approved"]),
                review_feedback=r["review_feedback"] or "",
                issue_after_review=r["issue_after_review"] or "",
                final_headline=r["final_headline"] or "",
                final_sector=r["final_sector"] or "",
            )
            for r in rows
        ]
