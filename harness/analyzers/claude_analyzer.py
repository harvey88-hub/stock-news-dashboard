"""
analyzers/claude_analyzer.py
=============================
Anthropic Claude 기반 3단계 AI 분석기.
기존 analyze.py의 step1 / step2 / step3 로직을 인터페이스 뒤로 감쌉니다.

Step 1 (Haiku)  : 시간대에서 핵심 이슈 1개 선정 + 관련 기사 추출
Step 2 (Sonnet) : 심층 분석 (배경·원인·전망 + 관련 종목)
Step 3          : StockMatcher에서 처리 (별도 모듈로 분리)
"""

from __future__ import annotations
import json
import time
from collections import defaultdict

from core.config import AppConfig
from core.interfaces import Article, AnalysisResult, StockMatch
from core.logging import get_logger
from core.errors import AnalyzerError


class ClaudeAnalyzer:
    """
    Claude를 사용하는 2단계 뉴스 분석기.

    Analyzer 프로토콜 구현::

        results = ClaudeAnalyzer(config).analyze(articles)
    """

    name = "claude"

    def __init__(self, config: AppConfig):
        if not config.anthropic_api_key:
            raise AnalyzerError("claude", "ANTHROPIC_API_KEY 환경 변수가 설정되지 않았습니다.")

        import anthropic
        self._claude  = anthropic.Anthropic(api_key=config.anthropic_api_key)
        self._cfg     = config.claude
        self._log     = get_logger("claude")

    # ──────────────────────────────────────
    # 공개 메서드 (Analyzer 프로토콜)
    # ──────────────────────────────────────

    def analyze(self, articles: list[Article], analyzed_hours: set[str] | None = None, **kwargs) -> list[AnalysisResult]:
        """
        기사 목록을 시간대별로 그룹화하여 분석합니다.

        Args:
            articles:       분석할 기사 목록
            analyzed_hours: 이미 분석된 시간대 집합 (스킵 용)

        Returns:
            AnalysisResult 목록 (시간대별 1개)
        """
        if not articles:
            return []

        analyzed_hours = analyzed_hours or set()

        # 시간대별 그룹화
        hour_map: dict[str, list[Article]] = defaultdict(list)
        for art in articles:
            key = art.hour_key()
            if key:
                hour_map[key].append(art)

        pending = sorted(
            [h for h in hour_map if h not in analyzed_hours],
            reverse=True,
        )

        self._log.info(f"시간대 {len(hour_map)}개 중 {len(pending)}개 미분석 → 분석 시작")

        results: list[AnalysisResult] = []
        for i, hour in enumerate(pending):
            hour_articles = hour_map[hour]
            self._log.info(f"  [{i+1}/{len(pending)}] {hour} ({len(hour_articles)}건)")
            result = self._analyze_hour(hour, hour_articles)
            if result:
                results.append(result)
            if i < len(pending) - 1:
                time.sleep(2)  # API rate limit 방지

        return results

    # ──────────────────────────────────────
    # 시간대 분석
    # ──────────────────────────────────────

    def _analyze_hour(self, hour: str, articles: list[Article]) -> AnalysisResult | None:
        """단일 시간대를 분석합니다."""
        try:
            # Step 1: 핵심 이슈 선정 + 관련 기사 추출 (Haiku)
            self._log.info("    [Step1] 핵심 이슈 선정 중...")
            key_articles = self._step1_find_key_issue(hour, articles)

            # Step 2: 심층 분석 (Sonnet)
            self._log.info("    [Step2] 심층 분석 중...")
            data = self._step2_deep_analysis(hour, key_articles)

            # 출처 정보 구성
            sources = list({a.source for a in articles})
            src_str = " · ".join(sources[:3]) + (
                f" 외 {len(sources)-3}건" if len(sources) > 3 else ""
            )

            result = AnalysisResult(
                hour=hour,
                sector=data.get("sector", "증권"),
                headline=data.get("headline", "주요 이슈"),
                ai_summary=data.get("ai_summary", ""),
                related_stocks=[
                    StockMatch(name=s.get("name", ""), reason=s.get("reason", ""))
                    for s in data.get("stocks", [])
                    if isinstance(s, dict) and s.get("name")
                ],
                article_count=len(articles),
                source_list=src_str,
            )

            self._log.info(f"    ✓ [{result.sector}] {result.headline}")
            return result

        except Exception as e:
            self._log.error(f"    시간대 {hour} 분석 실패: {e}")
            return None

    def _step1_find_key_issue(self, hour: str, articles: list[Article]) -> list[Article]:
        """Haiku로 시간대 핵심 이슈 1개를 선정하고 관련 기사를 반환합니다."""
        titles = "\n".join(
            f"{i}. [{a.source}] {a.title}"
            for i, a in enumerate(articles)
        )
        prompt = f"""{hour} 국내 증권 뉴스 {len(articles)}건입니다.

이 중 시장에 가장 큰 영향을 줄 핵심 이슈 1개를 선정하고,
그 이슈와 직접 관련된 기사 번호만 골라주세요.

반드시 JSON 형식으로만 응답하세요:
{{
  "issue": "핵심 이슈 한 줄 설명",
  "indices": [관련 기사 번호 목록]
}}

선정 기준:
- 가장 많은 언론사가 다루는 이슈
- 주가에 직접적인 영향을 줄 수 있는 이슈

기사 목록:
{titles}"""

        try:
            msg  = self._claude.messages.create(
                model=self._cfg.screening.model,
                max_tokens=self._cfg.screening.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            text    = self._extract_json_text(msg.content[0].text)
            res     = json.loads(text)
            indices = res.get("indices", [])
            selected = [articles[i] for i in indices if isinstance(i, int) and i < len(articles)]
            if selected:
                self._log.info(f"      핵심 이슈: {res.get('issue', '')} ({len(selected)}건 선별)")
                return selected
        except Exception as e:
            self._log.warning(f"      Step1 오류: {e} → 상위 5개로 대체")

        return articles[:5]

    def _step2_deep_analysis(self, hour: str, key_articles: list[Article]) -> dict:
        """Sonnet으로 선별된 기사를 심층 분석합니다."""
        articles_text = ""
        for i, a in enumerate(key_articles, 1):
            summary = (a.summary or "").strip()
            articles_text += f"\n[기사 {i}] [{a.source}] {a.title}\n"
            if summary:
                articles_text += f"본문: {summary[:400]}\n"

        prompt = f"""다음은 {hour}의 핵심 증권 뉴스입니다. 기사 제목과 본문을 모두 참고하여 분석해주세요.

반드시 아래 JSON 형식으로만 응답하세요 (설명 없이 JSON만):
{{
  "sector": "섹터명 1개 (반도체 / AI·로봇 / 2차전지 / 바이오 / 금융 / 에너지 / 자동차 / 유통 / 건설 등)",
  "headline": "핵심 이슈를 압축한 제목 (40자 이내, 명사형, 구체적 수치 포함 권장)",
  "ai_summary": "투자자 관점 심층 요약 3~4문장. 반드시 아래 순서로 작성:\\n1) 이슈 발생 배경 및 원인\\n2) 시장 및 관련 종목 영향\\n3) 향후 전망 또는 주목 포인트",
  "stocks": [
    {{"name": "종목명", "reason": "이 종목이 이슈와 관련된 구체적 이유 (20자 이내)"}},
    {{"name": "종목명", "reason": "이유"}}
  ]
}}

작성 기준:
- ai_summary: 단순 제목 나열 금지, 본문 내용 기반으로 깊이있게 서술
- stocks: 기사에서 직접 언급되거나 명백히 영향받는 종목만, 최대 5개
          반드시 정확한 한국 상장 종목명으로 작성

핵심 기사:
{articles_text}"""

        try:
            msg  = self._claude.messages.create(
                model=self._cfg.deep_analysis.model,
                max_tokens=self._cfg.deep_analysis.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            text = self._extract_json_text(msg.content[0].text)
            res  = json.loads(text)

            stocks = []
            for s in res.get("stocks", []):
                if isinstance(s, dict) and s.get("name"):
                    stocks.append({"name": s["name"].strip(), "reason": s.get("reason", "").strip()})
                elif isinstance(s, str) and s.strip():
                    stocks.append({"name": s.strip(), "reason": ""})

            return {
                "sector":     res.get("sector", "증권"),
                "headline":   res.get("headline", "주요 이슈"),
                "ai_summary": res.get("ai_summary", ""),
                "stocks":     stocks,
            }

        except Exception as e:
            self._log.error(f"Step2 오류: {e}")
            return {
                "sector": "증권", "headline": "AI 분석 오류",
                "ai_summary": "분석 중 오류가 발생했습니다.", "stocks": [],
            }

    @staticmethod
    def _extract_json_text(text: str) -> str:
        """응답 텍스트에서 JSON 부분만 추출합니다."""
        text = text.strip()
        if "```" in text:
            parts = text.split("```")
            text  = parts[1] if len(parts) > 1 else text
            if text.lower().startswith("json"):
                text = text[4:]
        return text.strip()
