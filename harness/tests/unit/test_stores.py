"""
tests/unit/test_stores.py
==========================
SQLiteStore 단위 테스트.
실제 Supabase 없이 로컬 SQLite로 Store 인터페이스를 검증합니다.
"""

import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.config import AppConfig, StoreConfig
from core.interfaces import Article, AnalysisResult, StockMatch, ListedStock
from stores.sqlite_store import SQLiteStore

KST = timezone(timedelta(hours=9))


# ──────────────────────────────────────────
# 픽스처
# ──────────────────────────────────────────

@pytest.fixture
def tmp_store():
    """임시 SQLiteStore (로컬 /tmp 사용으로 권한 문제 우회)"""
    import tempfile, os
    fd, db_path = tempfile.mkstemp(suffix=".db", dir="/tmp")
    os.close(fd)
    cfg = AppConfig()
    cfg.store = StoreConfig(sqlite_path=db_path)
    store = SQLiteStore(cfg)
    yield store
    os.unlink(db_path)


@pytest.fixture
def sample_articles():
    now = datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    return [
        Article(
            source="테스트뉴스",
            title="삼성전자, HBM4 양산",
            link="http://example.com/1",
            published_at=now,
            collected_at=now,
            summary="삼성전자 관련 뉴스",
        ),
        Article(
            source="한국경제",
            title="SK하이닉스 실적 발표",
            link="http://example.com/2",
            published_at=now,
            collected_at=now,
        ),
    ]


@pytest.fixture
def sample_analyses():
    now = datetime.now(KST).strftime("%Y-%m-%d %H:00")
    return [
        AnalysisResult(
            hour=now,
            sector="반도체",
            headline="HBM 공급 확대로 관련주 강세",
            ai_summary="반도체 업황 개선 예상.",
            related_stocks=[
                StockMatch(name="삼성전자", reason="HBM 주요 공급사"),
                StockMatch(name="SK하이닉스", reason="HBM 1위"),
            ],
            article_count=5,
            source_list="테스트뉴스 · 한국경제",
        ),
    ]


# ──────────────────────────────────────────
# SQLiteStore 테스트
# ──────────────────────────────────────────

class TestSQLiteStore:

    def test_save_and_get_articles(self, tmp_store, sample_articles):
        """기사 저장 후 조회 시 동일한 데이터가 반환되어야 한다"""
        saved = tmp_store.save_articles(sample_articles)
        assert saved == 2

        retrieved = tmp_store.get_articles(hours_back=24)
        assert len(retrieved) == 2
        titles = {a.title for a in retrieved}
        assert "삼성전자, HBM4 양산" in titles

    def test_save_and_get_analyses(self, tmp_store, sample_analyses):
        """분석 결과 저장 후 조회 시 동일한 데이터가 반환되어야 한다"""
        saved = tmp_store.save_analyses(sample_analyses)
        assert saved == 1

        retrieved = tmp_store.get_analyses(hours_back=24)
        assert len(retrieved) == 1
        assert retrieved[0].sector == "반도체"
        assert len(retrieved[0].related_stocks) == 2

    def test_save_and_get_stocks(self, tmp_store):
        """종목 저장 후 딕셔너리로 조회가 가능해야 한다"""
        stocks = [
            ListedStock(stock_code="005930", stock_name="삼성전자", market="KOSPI"),
            ListedStock(stock_code="000660", stock_name="SK하이닉스", market="KOSPI"),
        ]
        tmp_store.save_stocks(stocks)

        listed = tmp_store.get_listed_stocks()
        assert "삼성전자" in listed
        assert listed["삼성전자"] == "005930"

    def test_get_analyzed_hours(self, tmp_store, sample_analyses):
        """분석된 시간대 집합이 정확해야 한다"""
        tmp_store.save_analyses(sample_analyses)

        hours = tmp_store.get_analyzed_hours(hours_back=24)
        assert sample_analyses[0].hour in hours

    def test_upsert_deduplicates(self, tmp_store, sample_articles):
        """같은 링크로 두 번 저장해도 중복이 생기지 않아야 한다"""
        tmp_store.save_articles(sample_articles)
        tmp_store.save_articles(sample_articles)  # 동일 데이터 재저장

        retrieved = tmp_store.get_articles(hours_back=24)
        assert len(retrieved) == 2, "중복 저장이 발생함"

    def test_empty_save_returns_zero(self, tmp_store):
        """빈 목록 저장 시 0을 반환해야 한다"""
        assert tmp_store.save_articles([]) == 0
        assert tmp_store.save_analyses([]) == 0
        assert tmp_store.save_stocks([]) == 0

    def test_stocks_as_dicts(self, tmp_store, sample_analyses):
        """AnalysisResult.stocks_as_dicts()가 올바른 형식을 반환해야 한다"""
        result = sample_analyses[0]
        dicts  = result.stocks_as_dicts()
        assert isinstance(dicts, list)
        assert all(isinstance(d, dict) for d in dicts)
        assert dicts[0]["name"] == "삼성전자"
