"""
pipelines/daily_summary.py
===========================
매일 1회 (장 마감 후) 실행되는 일일 브리핑 요약 파이프라인.

흐름:
  1. Store에서 하루치 AnalysisResult 조회
  2. Claude Sonnet으로 종합 분석
     - top_issues  : 오늘의 핵심 이슈 3개 (임팩트 점수 상위)
     - market_flow : 하루 흐름 요약 3줄
     - hot_sectors : 주목 섹터 최대 3개
     - hot_stocks  : 가장 많이 언급된 종목 상위 5개
  3. DailySummary를 Store에 저장
"""

from __future__ import annotations
import json
from collections import Counter
from datetime import datetime, timezone, timedelta

from core.interfaces import AnalysisResult, DailySummary
from core.logging import PipelineLogger

_KST = timezone(timedelta(hours=9))


class DailySummaryPipeline:
    """
    일일 브리핑 요약 파이프라인.

    Harness가 아래 의존성을 주입합니다:
    - analyzers["claude"] : ClaudeAnalyzer (Sonnet 모델 사용)
    - store               : Store (Supabase or SQLite)
    - config              : AppConfig
    """

    name = "daily_summary"

    def __init__(self, collectors, analyzers, store, config):
        self._claude  = analyzers.get("claude")
        self._store   = store
        self._config  = config

    def execute(self, dry_run: bool = False, plog: PipelineLogger | None = None) -> dict:
        """
        파이프라인을 실행합니다.

        Args:
            dry_run: True이면 DB 저장 없이 시뮬레이션만 수행
            plog:    진행 로그 핸들러

        Returns:
            {"analyses_used": int, "saved": bool, "date": str}
        """
        log = plog or PipelineLogger(self.name)
        today_kst = datetime.now(_KST).strftime("%Y-%m-%d")
        summary_dict = {"analyses_used": 0, "saved": False, "date": today_kst}

        # ── Step 1: 오늘 하루치 분석 결과 조회 ──────────────
        log.step(f"{today_kst} 분석 결과 조회 중...")
        try:
            analyses = self._store.get_analyses(hours_back=24)
        except Exception as e:
            log.error("분석 결과 조회 실패", exc=e)
            return summary_dict

        # 오늘 날짜 분석 결과만 필터링
        today_analyses = [
            r for r in analyses
            if r.hour.startswith(today_kst)
        ]

        if not today_analyses:
            log.warn(f"{today_kst} 분석 결과 없음 — 파이프라인 종료")
            return summary_dict

        summary_dict["analyses_used"] = len(today_analyses)
        log.success(f"{len(today_analyses)}건 분석 결과 로드 완료")

        # ── Step 2: 핫 종목 집계 (언급 횟수 기반) ────────────
        log.step("핫 종목 집계 중...")
        stock_counter: Counter = Counter()
        stock_codes: dict[str, str] = {}
        for r in today_analyses:
            for s in r.related_stocks:
                if s.name:
                    stock_counter[s.name] += 1
                    if s.code and s.name not in stock_codes:
                        stock_codes[s.name] = s.code

        hot_stocks_raw = [
            {
                "name": name,
                "code": stock_codes.get(name, ""),
                "mention_count": count,
            }
            for name, count in stock_counter.most_common(5)
        ]

        # ── Step 3: Claude Sonnet으로 종합 분석 ──────────────
        log.step("Claude Sonnet 종합 분석 중...")
        if not self._claude:
            log.warn("ClaudeAnalyzer 없음 — AI 분석 스킵")
            daily = self._build_fallback_summary(today_kst, today_analyses, hot_stocks_raw)
        else:
            try:
                daily = self._generate_daily_summary(
                    today_kst, today_analyses, hot_stocks_raw
                )
            except Exception as e:
                log.warn(f"AI 분석 실패 ({e}) → 폴백 요약 사용")
                daily = self._build_fallback_summary(today_kst, today_analyses, hot_stocks_raw)

        log.success(
            f"일일 요약 생성 완료 "
            f"(top_issues: {len(daily.top_issues)}개, "
            f"hot_sectors: {len(daily.hot_sectors)}개, "
            f"hot_stocks: {len(daily.hot_stocks)}개)"
        )

        # ── Step 4: 저장 ──────────────────────────────────
        if not dry_run:
            log.step("일일 요약 저장 중...")
            try:
                saved = self._store.save_daily_summary(daily)
                summary_dict["saved"] = saved
                if saved:
                    log.success(f"{today_kst} 일일 요약 저장 완료")
                else:
                    log.warn("일일 요약 저장 실패")
            except Exception as e:
                log.error("일일 요약 저장 실패", exc=e)
        else:
            log.step("[dry-run] 저장 스킵")
            summary_dict["saved"] = False

        return summary_dict

    # ──────────────────────────────────────
    # AI 종합 분석
    # ──────────────────────────────────────

    def _generate_daily_summary(
        self,
        date: str,
        analyses: list[AnalysisResult],
        hot_stocks_raw: list[dict],
    ) -> DailySummary:
        """Claude Sonnet으로 하루치 분석 결과를 종합합니다."""
        # 임팩트 점수 기준 상위 이슈 정렬
        sorted_analyses = sorted(analyses, key=lambda r: r.impact_score, reverse=True)

        issues_text = "\n".join(
            f"[{i+1}] [{r.sector}] {r.headline} (임팩트: {r.impact_score}/10, {r.hour})\n"
            f"    요약: {r.ai_summary[:200]}"
            for i, r in enumerate(sorted_analyses[:10])
        )

        hot_stocks_text = ", ".join(
            f"{s['name']}({s['mention_count']}회)" for s in hot_stocks_raw
        ) or "없음"

        prompt = f"""{date} 국내 증권 시장 하루치 이슈 분석 결과입니다.

오늘의 이슈 목록 (임팩트 점수 상위 순):
{issues_text}

가장 많이 언급된 종목: {hot_stocks_text}

위 내용을 바탕으로 아래 형식으로 일일 브리핑을 작성해주세요.

반드시 JSON으로만 응답:
{{
  "top_issues": [
    {{"headline": "핵심 이슈 제목 (40자 이내)", "sector": "섹터명", "impact_score": 임팩트점수}},
    {{"headline": "...", "sector": "...", "impact_score": ...}},
    {{"headline": "...", "sector": "...", "impact_score": ...}}
  ],
  "market_flow": "오늘 시장 흐름을 3줄로 요약 (각 줄은 \\n으로 구분). 주요 상승/하락 동인, 섹터별 흐름, 투자자 주목 포인트 포함",
  "hot_sectors": ["섹터1", "섹터2", "섹터3"],
  "hot_stocks_commentary": "언급 빈도 상위 종목들의 공통 테마나 이유 2줄 이내"
}}

작성 기준:
- top_issues: 임팩트 점수 상위 3개 선택
- market_flow: 단순 종목 나열 금지, 시장 맥락과 의미 중심
- hot_sectors: 오늘 가장 활발히 거론된 섹터 최대 3개"""

        msg = self._claude._claude.messages.create(
            model=self._claude._cfg.deep_analysis.model,
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        text = self._claude._extract_json_text(msg.content[0].text)
        res = json.loads(text)

        # top_issues 구성 (AI 응답 우선, 폴백: 임팩트 상위 3개)
        top_issues = []
        for item in res.get("top_issues", [])[:3]:
            if isinstance(item, dict) and item.get("headline"):
                top_issues.append({
                    "headline": item.get("headline", ""),
                    "sector":   item.get("sector", ""),
                    "impact_score": int(item.get("impact_score", 0)),
                })
        if not top_issues:
            top_issues = [
                {"headline": r.headline, "sector": r.sector, "impact_score": r.impact_score}
                for r in sorted_analyses[:3]
            ]

        hot_sectors = [s for s in res.get("hot_sectors", []) if isinstance(s, str)][:3]
        if not hot_sectors:
            sector_counter: Counter = Counter(r.sector for r in analyses if r.sector)
            hot_sectors = [s for s, _ in sector_counter.most_common(3)]

        market_flow = res.get("market_flow", "")

        return DailySummary(
            date=date,
            created_at=datetime.now(_KST).strftime("%Y-%m-%d %H:%M:%S"),
            top_issues=top_issues,
            market_flow=market_flow,
            hot_sectors=hot_sectors,
            hot_stocks=hot_stocks_raw,
        )

    def _build_fallback_summary(
        self,
        date: str,
        analyses: list[AnalysisResult],
        hot_stocks_raw: list[dict],
    ) -> DailySummary:
        """AI 없이 집계 기반으로 DailySummary를 구성합니다."""
        sorted_analyses = sorted(analyses, key=lambda r: r.impact_score, reverse=True)

        top_issues = [
            {"headline": r.headline, "sector": r.sector, "impact_score": r.impact_score}
            for r in sorted_analyses[:3]
        ]

        sector_counter: Counter = Counter(r.sector for r in analyses if r.sector)
        hot_sectors = [s for s, _ in sector_counter.most_common(3)]

        return DailySummary(
            date=date,
            created_at=datetime.now(_KST).strftime("%Y-%m-%d %H:%M:%S"),
            top_issues=top_issues,
            market_flow="",
            hot_sectors=hot_sectors,
            hot_stocks=hot_stocks_raw,
        )
