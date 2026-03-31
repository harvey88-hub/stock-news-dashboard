"""
tests/unit/test_analyzers.py
==============================
StockMatcher 단위 테스트.
Claude API 없이 매칭 로직만 검증합니다.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.config import AppConfig, ClaudeAnalyzerConfig, ClaudeModelConfig
from core.interfaces import AnalysisResult, StockMatch
from analyzers.stock_matcher import StockMatcher

KST = timezone(timedelta(hours=9))


# ──────────────────────────────────────────
# 픽스처
# ──────────────────────────────────────────

@pytest.fixture
def mock_config():
    cfg = AppConfig()
    cfg.anthropic_api_key = ""   # API 호출 없이 테스트
    cfg.claude = ClaudeAnalyzerConfig(
        stock_fallback=ClaudeModelConfig(model="claude-haiku-4-5", max_tokens=300),
    )
    return cfg


@pytest.fixture
def listed_stocks():
    return {
        "삼성전자":  "005930",
        "SK하이닉스": "000660",
        "카카오":    "035720",
        "현대차":    "005380",
        "LG에너지솔루션": "373220",
    }


@pytest.fixture
def sample_result():
    now = datetime.now(KST).strftime("%Y-%m-%d %H:00")
    return AnalysisResult(
        hour=now,
        sector="반도체",
        headline="HBM 수급 이슈",
        ai_summary="메모리 반도체 시장 이슈.",
        related_stocks=[
            StockMatch(name="삼성전자", reason="HBM 공급사"),
            StockMatch(name="SK하이닉스", reason="HBM 1위"),
            StockMatch(name="두나무", reason="비상장 기업"),   # DB 미매칭 예상
        ],
    )


# ──────────────────────────────────────────
# StockMatcher 테스트
# ──────────────────────────────────────────

class TestStockMatcher:

    def test_exact_match(self, mock_config, listed_stocks, sample_result):
        """정확히 일치하는 종목은 그대로 유지되어야 한다"""
        matcher = StockMatcher(mock_config)
        results = matcher.match([sample_result], listed_stocks)

        names = [s.name for s in results[0].related_stocks]
        assert "삼성전자" in names
        assert "SK하이닉스" in names

    def test_unlisted_company_removed(self, mock_config, listed_stocks, sample_result):
        """비상장 기업은 AI 보조 없이 제거되어야 한다 (API 키 없음)"""
        matcher = StockMatcher(mock_config)
        results = matcher.match([sample_result], listed_stocks)

        names = [s.name for s in results[0].related_stocks]
        assert "두나무" not in names

    def test_fuzzy_match(self, mock_config, listed_stocks):
        """유사한 이름도 매칭되어야 한다"""
        now = datetime.now(KST).strftime("%Y-%m-%d %H:00")
        result = AnalysisResult(
            hour=now, sector="반도체", headline="테스트",
            ai_summary="테스트",
            related_stocks=[
                StockMatch(name="삼성전자(주)", reason="테스트"),   # 부분 매칭
            ],
        )
        matcher = StockMatcher(mock_config)
        results = matcher.match([result], listed_stocks)
        names   = [s.name for s in results[0].related_stocks]
        assert len(names) > 0, "유사 이름 매칭이 동작하지 않음"

    def test_empty_listed_stocks_skips(self, mock_config, sample_result):
        """종목 DB가 비어있으면 매칭 없이 원본 반환"""
        matcher = StockMatcher(mock_config)
        results = matcher.match([sample_result], {})
        # 경고만 출력하고 원본 그대로 반환
        assert results[0] is sample_result

    def test_stock_code_filled(self, mock_config, listed_stocks):
        """매칭된 종목의 코드가 채워져야 한다"""
        now = datetime.now(KST).strftime("%Y-%m-%d %H:00")
        result = AnalysisResult(
            hour=now, sector="반도체", headline="테스트",
            ai_summary="",
            related_stocks=[StockMatch(name="삼성전자", reason="테스트")],
        )
        matcher = StockMatcher(mock_config)
        results = matcher.match([result], listed_stocks)
        samsung = next((s for s in results[0].related_stocks if s.name == "삼성전자"), None)
        assert samsung is not None
        assert samsung.code == "005930"
