"""
core/interfaces.py
==================
Harness가 각 모듈에 기대하는 표준 인터페이스(프로토콜)를 정의합니다.
모든 Collector / Analyzer / Store 구현체는 여기서 정의한 프로토콜을 따라야 합니다.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable


# ──────────────────────────────────────────
# 공통 데이터 모델
# ──────────────────────────────────────────

@dataclass
class Article:
    """뉴스 기사 공통 데이터 모델"""
    source: str
    title: str
    link: str
    published_at: str           # KST 문자열 "YYYY-MM-DD HH:MM"
    collected_at: str           # KST 문자열 "YYYY-MM-DD HH:MM"
    summary: str = ""
    pubdate_raw: str = ""
    ai_analysis: dict = field(default_factory=dict)

    def hour_key(self) -> str:
        """시간대 키 반환 ('2026-03-30 09:00' 형식)"""
        ts = self.collected_at or self.published_at
        return ts[:13] + ":00" if ts else ""


@dataclass
class StockMatch:
    """분석 결과 종목 매칭"""
    name: str
    reason: str
    code: str = ""              # 종목 코드 (DB 매칭 후 채워짐)


@dataclass
class AnalysisResult:
    """AI 분석 결과 공통 모델"""
    hour: str
    sector: str
    headline: str
    ai_summary: str
    related_stocks: list[StockMatch] = field(default_factory=list)
    article_count: int = 0
    source_list: str = ""

    def stocks_as_dicts(self) -> list[dict]:
        return [{"name": s.name, "reason": s.reason} for s in self.related_stocks]


@dataclass
class ListedStock:
    """상장 종목 정보"""
    stock_code: str
    stock_name: str
    market: str = ""
    corp_name: str = ""
    isin_code: str = ""


# ──────────────────────────────────────────
# 프로토콜 (인터페이스)
# ──────────────────────────────────────────

@runtime_checkable
class Collector(Protocol):
    """데이터 수집기 인터페이스"""

    name: str

    def collect(self, **kwargs) -> list[Article]:
        """데이터를 수집하고 Article 리스트를 반환한다."""
        ...


@runtime_checkable
class Analyzer(Protocol):
    """AI 분석기 인터페이스"""

    name: str

    def analyze(self, articles: list[Article], **kwargs) -> list[AnalysisResult]:
        """기사 목록을 분석하고 AnalysisResult 리스트를 반환한다."""
        ...


@runtime_checkable
class Store(Protocol):
    """저장소 인터페이스"""

    # ── 쓰기 ──
    def save_articles(self, articles: list[Article]) -> int:
        """기사를 저장하고 실제 저장된 건수를 반환한다."""
        ...

    def save_analyses(self, results: list[AnalysisResult]) -> int:
        """분석 결과를 저장하고 실제 저장된 건수를 반환한다."""
        ...

    def save_stocks(self, stocks: list[ListedStock]) -> int:
        """상장 종목 목록을 저장하고 실제 저장된 건수를 반환한다."""
        ...

    # ── 읽기 ──
    def get_articles(self, hours_back: int = 24) -> list[Article]:
        """최근 N시간 이내 기사를 반환한다."""
        ...

    def get_analyses(self, hours_back: int = 24) -> list[AnalysisResult]:
        """최근 N시간 이내 분석 결과를 반환한다."""
        ...

    def get_listed_stocks(self) -> dict[str, str]:
        """{종목명: 종목코드} 딕셔너리를 반환한다."""
        ...

    def get_analyzed_hours(self, hours_back: int = 24) -> set[str]:
        """이미 분석된 시간대 키 집합을 반환한다."""
        ...
