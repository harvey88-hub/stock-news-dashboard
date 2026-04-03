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
    source: str = "article"     # "article": 기사 언급 종목 / "ai": AI 판단 관련 종목


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
    impact_score: int = 0           # 이슈 임팩트 점수 0~10
    is_evolution: bool = False       # 기존 이슈의 발전(후속/갱신/반전) 여부
    evolution_type: str = ""         # "update" | "reversal" | "followup" | ""

    def stocks_as_dicts(self) -> list[dict]:
        return [{"name": s.name, "reason": s.reason, "source": s.source} for s in self.related_stocks]


@dataclass
class DailySummary:
    """일일 브리핑 요약 — 하루치 분석 결과를 종합한 모델"""
    date: str                                    # "YYYY-MM-DD"
    created_at: str                              # KST 문자열
    top_issues: list[dict] = field(default_factory=list)    # [{"headline": str, "sector": str, "impact_score": int}]
    market_flow: str = ""                        # 하루 흐름 요약 3줄
    hot_sectors: list[str] = field(default_factory=list)    # 주목 섹터 최대 3개
    hot_stocks: list[dict] = field(default_factory=list)    # [{"name": str, "code": str, "mention_count": int}]


@dataclass
class ListedStock:
    """상장 종목 정보"""
    stock_code: str
    stock_name: str
    market: str = ""
    corp_name: str = ""
    isin_code: str = ""


@dataclass
class AnalysisTrace:
    """AI 분석 과정 추적 로그 — 각 단계에서 AI가 본 데이터와 내린 판단을 기록합니다."""
    hour: str
    created_at: str

    # Step 1 : 이슈 선정 (Haiku)
    input_article_count: int = 0
    input_articles: list[dict] = field(default_factory=list)    # [{source, title}]
    step1_issue: str = ""
    step1_filtered_count: int = 0

    # Step 0 : 사전 필터링 (Haiku)
    step0_removed_count: int = 0                                # 필터링으로 제거된 기사 수
    step0_removal_reasons: list[str] = field(default_factory=list)  # 제거 사유 목록

    # Step 1b : 유사도 검사 (Haiku)
    similarity_checked: bool = False
    compared_headlines: list[str] = field(default_factory=list) # 비교 대상 헤드라인
    is_duplicate: bool = False
    similar_to: str = ""                                        # 유사 판정된 기존 헤드라인
    similarity_reason: str = ""
    retry_count: int = 0                                        # 재선정 횟수
    issue_after_dedup: str = ""                                 # 유사도 통과 후 이슈
    is_evolution: bool = False                                  # 발전 이슈 여부
    evolution_of: str = ""                                      # 발전 대상 기존 헤드라인
    evolution_type: str = ""                                    # "update" | "reversal" | "followup"

    # Step 1c : 검토 Agent (Haiku)
    review_approved: bool = True
    review_feedback: str = ""
    issue_after_review: str = ""                                # 검토 후 최종 이슈

    # Step 2 : 심층 분석 결과 (Sonnet)
    final_headline: str = ""
    final_sector: str = ""

    # Step 2b : 팩트체크 (Haiku)
    factcheck_passed: bool = True
    factcheck_corrections: list[str] = field(default_factory=list)  # 수정된 항목 목록
    headline_before_factcheck: str = ""

    # Step 2c : ai_summary 품질 검토 (Haiku)
    summary_quality_passed: bool = True
    summary_regenerated: bool = False
    summary_quality_feedback: str = ""

    # 이슈 중요도 스코어링 (Haiku)
    impact_score: int = 0
    impact_score_reason: str = ""

    # 주요 이슈 없음
    skipped: bool = False          # True이면 이슈 없음으로 Step 2 없이 종료
    no_issue_reason: str = ""      # AI가 판단한 이슈 없음 사유


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

    def save_traces(self, traces: list[AnalysisTrace]) -> int:
        """AI 분석 과정 추적 로그를 저장하고 저장된 건수를 반환한다."""
        ...

    def get_traces(self, hours_back: int = 24) -> list[AnalysisTrace]:
        """최근 N시간 이내 분석 추적 로그를 반환한다."""
        ...

    def save_daily_summary(self, summary: DailySummary) -> bool:
        """일일 브리핑 요약을 저장하고 성공 여부를 반환한다."""
        ...

    def get_daily_summary(self, date: str) -> DailySummary | None:
        """특정 날짜(YYYY-MM-DD)의 일일 브리핑 요약을 반환한다. 없으면 None."""
        ...
