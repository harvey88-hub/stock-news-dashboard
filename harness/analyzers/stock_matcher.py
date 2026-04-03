"""
analyzers/stock_matcher.py
===========================
종목 매칭 분석기.
기존 analyze.py의 step3_verify_stocks / step3_ai_fallback 로직을 분리합니다.

3단계 매칭 전략:
1. 정확한 이름 매칭 (DB lookup)
2. difflib 유사 매칭 (85% 이상)
3. 부분 문자열 매칭
4. AI 보조 (Haiku) — 비상장 기업 → 관련 상장사 탐색
"""

from __future__ import annotations
import json
import difflib

from core.config import AppConfig
from core.interfaces import AnalysisResult, StockMatch
from core.logging import get_logger


class StockMatcher:
    """
    DB 상장 종목 리스트를 기반으로 분석 결과의 종목을 검증/보완합니다.

    사용::

        matcher = StockMatcher(config)
        results = matcher.match(results, listed_stocks)
    """

    name = "stock_matcher"

    def __init__(self, config: AppConfig):
        self._cutoff = config.raw.get("analyzers", {}).get("stock_matcher", {}).get("similarity_cutoff", 0.85) \
            if hasattr(config, "raw") else 0.85
        self._anthropic_key = config.anthropic_api_key
        self._log = get_logger("stock_matcher")

        # Claude 클라이언트 (AI 보조용, 선택적)
        self._claude = None
        if self._anthropic_key:
            try:
                import anthropic
                self._claude = anthropic.Anthropic(api_key=self._anthropic_key)
            except ImportError:
                pass

        # Haiku 모델명
        self._haiku_model = config.claude.stock_fallback.model

    # ──────────────────────────────────────
    # 공개 메서드
    # ──────────────────────────────────────

    def match(
        self,
        results: list[AnalysisResult],
        listed_stocks: dict[str, str],
    ) -> list[AnalysisResult]:
        """
        AnalysisResult 목록의 related_stocks를 검증하고 보완합니다.

        Args:
            results:       분석 결과 목록
            listed_stocks: {종목명: 종목코드} 딕셔너리

        Returns:
            related_stocks가 검증된 AnalysisResult 목록
        """
        if not listed_stocks:
            self._log.warning("상장 종목 DB 없음 — 종목 검증 스킵")
            return results

        stock_names = list(listed_stocks.keys())

        for result in results:
            if result.related_stocks:
                before = [s.name for s in result.related_stocks]
                verified = self._verify_stocks(result.related_stocks, listed_stocks, stock_names)

                # 종목 코드 채우기
                for stock in verified:
                    if not stock.code and stock.name in listed_stocks:
                        stock.code = listed_stocks[stock.name]

                # 종목 관련성 검증 Agent — 관련성 낮은 종목 제거
                if verified and self._claude:
                    verified = self._relevance_check_agent(
                        result.headline, verified, result.sector
                    )

                result.related_stocks = verified
                after = [s.name for s in verified]
                self._log.info(f"  {result.hour} 종목 검증: {before} → {after}")

            # 종목이 없으면 이슈 관련 종목 탐색 Agent 실행
            if not result.related_stocks and self._claude:
                self._log.info(f"  {result.hour} 관련 종목 없음 → 이슈 종목 탐색 Agent 실행")
                issue_stocks = self._issue_stock_agent(result.headline, result.sector, listed_stocks, stock_names)
                for stock in issue_stocks:
                    if not stock.code and stock.name in listed_stocks:
                        stock.code = listed_stocks[stock.name]
                result.related_stocks = issue_stocks
                self._log.info(f"  {result.hour} 이슈 종목 탐색 결과: {[s.name for s in issue_stocks]}")

        return results

    def analyze(self, articles, **kwargs) -> list:
        """Analyzer 프로토콜 호환용 — 직접 사용 시 match()를 사용하세요."""
        return []

    # ──────────────────────────────────────
    # 내부 매칭 로직
    # ──────────────────────────────────────

    def _verify_stocks(
        self,
        stocks: list[StockMatch],
        listed: dict[str, str],
        stock_names: list[str],
    ) -> list[StockMatch]:
        """3단계 DB 매칭 + AI 보조 방식으로 종목을 검증합니다."""
        verified:  list[StockMatch] = []
        unmatched: list[StockMatch] = []
        seen:      set[str]         = set()

        for stock in stocks:
            name = stock.name.strip()
            if not name or name in seen:
                continue

            matched = self._match_one(name, listed, stock_names)
            if matched:
                if matched not in seen:
                    verified.append(StockMatch(name=matched, reason=stock.reason))
                    seen.add(matched)
            else:
                unmatched.append(stock)

        # AI 보조 (비상장 기업 → 관련 상장사 탐색)
        if unmatched and self._claude:
            self._log.info(f"  DB 미매칭 {len(unmatched)}건 → AI 보조 탐색")
            ai_results = self._ai_fallback(unmatched)
            for item in ai_results:
                if item.name and item.name in listed and item.name not in seen:
                    verified.append(item)
                    seen.add(item.name)

        return verified

    def _match_one(
        self,
        name: str,
        listed: dict[str, str],
        stock_names: list[str],
    ) -> str | None:
        """1~3단계 매칭을 수행합니다. 매칭된 종목명 또는 None을 반환합니다."""
        # 1단계: 정확한 이름
        if name in listed:
            return name

        # 2단계: difflib 유사 매칭
        close = difflib.get_close_matches(name, stock_names, n=1, cutoff=self._cutoff)
        if close:
            return close[0]

        # 3단계: 부분 문자열 매칭
        clean = name.replace(" ", "").replace("(주)", "").replace("㈜", "")
        partial = [
            n for n in stock_names
            if clean in n.replace(" ", "") or n.replace(" ", "") in clean
        ]
        if partial:
            return min(partial, key=len)

        return None

    def _issue_stock_agent(
        self,
        headline: str,
        sector: str,
        listed: dict[str, str],
        stock_names: list[str],
    ) -> list[StockMatch]:
        """이슈 헤드라인과 섹터를 기반으로 관련 종목을 탐색합니다.

        Step 2에서 관련 종목을 추출하지 못했거나 DB 매칭이 모두 실패한 경우 호출됩니다.
        이슈 내용을 분석하여 관련성이 높은 상장 종목을 제안하고 DB에서 검증합니다.
        """
        if not self._claude or not headline:
            return []

        prompt = f"""다음 이슈와 직접적으로 관련된 KOSPI/KOSDAQ 상장 종목을 찾아주세요.

이슈: {headline}
섹터: {sector}

이슈 내용을 분석하여 직접 영향을 받을 한국 상장 종목을 최대 5개 선정하세요.
- 이슈에서 언급된 업종·사업·테마와 관련된 대표 종목
- 반드시 실제 KOSPI/KOSDAQ 상장 종목명으로 작성

반드시 JSON 배열로만 응답 (없으면 빈 배열 []):
[
  {{"name": "상장종목명", "reason": "이슈 관련 이유 20자 이내"}},
  ...
]"""

        try:
            msg = self._claude.messages.create(
                model=self._haiku_model,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            text = msg.content[0].text.strip()
            if "```" in text:
                parts = text.split("```")
                text  = parts[1] if len(parts) > 1 else text
                if text.lower().startswith("json"):
                    text = text[4:]
            if "[" in text:
                text = text[text.index("["):text.rindex("]") + 1]

            seen: set[str] = set()
            out:  list[StockMatch] = []
            for item in json.loads(text):
                if not isinstance(item, dict):
                    continue
                name = item.get("name", "").strip()
                if not name or name in seen:
                    continue
                # DB에서 검증
                matched = self._match_one(name, listed, stock_names)
                if matched and matched not in seen:
                    seen.add(matched)
                    out.append(StockMatch(name=matched, reason=item.get("reason", "").strip(), source="ai"))

            return out
        except Exception as e:
            self._log.warning(f"이슈 종목 탐색 Agent 오류: {e}")
            return []

    def _relevance_check_agent(
        self,
        headline: str,
        stocks: list[StockMatch],
        sector: str,
    ) -> list[StockMatch]:
        """Haiku로 DB 매칭 통과 종목들의 실제 이슈 관련성을 재검토합니다.

        관련성 점수 5 미만인 종목을 제거합니다.

        Returns:
            관련성 낮은 종목이 제거된 StockMatch 목록
        """
        if not self._claude or not stocks:
            return stocks

        stocks_info = [{"name": s.name, "reason": s.reason, "source": s.source} for s in stocks]
        prompt = f"""아래 이슈와 각 종목의 관련성을 0~10점으로 평가해주세요.

이슈: {headline}
섹터: {sector}

종목 목록:
{json.dumps(stocks_info, ensure_ascii=False, indent=2)}

평가 기준:
- 10: 이슈의 직접 당사자 기업
- 8~9: 이슈에서 직접 언급된 기업 또는 공급망 핵심 업체
- 5~7: 이슈 섹터의 대표 종목으로 간접 영향
- 0~4: 이슈와 관련성이 낮거나 근거 없음

반드시 JSON 배열로만 응답:
[
  {{"name": "종목명", "score": 점수(0~10), "keep": true/false}},
  ...
]
(score >= 5 이면 keep: true, score < 5 이면 keep: false)"""

        try:
            msg = self._claude.messages.create(
                model=self._haiku_model,
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            text = msg.content[0].text.strip()
            if "```" in text:
                parts = text.split("```")
                text  = parts[1] if len(parts) > 1 else text
                if text.lower().startswith("json"):
                    text = text[4:]
            if "[" in text:
                text = text[text.index("["):text.rindex("]") + 1]

            evaluations: dict[str, bool] = {}
            for item in json.loads(text):
                if not isinstance(item, dict):
                    continue
                name = item.get("name", "").strip()
                keep = bool(item.get("keep", True))
                score = item.get("score", 5)
                if name:
                    evaluations[name] = keep
                    if not keep:
                        self._log.info(
                            f"  관련성 낮음 제거: {name} (점수 {score})"
                        )

            # 관련성 낮은 종목 제거 (평가 결과가 없으면 유지)
            filtered = [s for s in stocks if evaluations.get(s.name, True)]
            removed = len(stocks) - len(filtered)
            if removed:
                self._log.info(f"  관련성 검증 후 {removed}개 종목 제거 (총 {len(filtered)}개 유지)")
            return filtered

        except Exception as e:
            self._log.warning(f"  관련성 검증 Agent 오류: {e} → 원본 종목 유지")
            return stocks

    def _ai_fallback(self, stocks: list[StockMatch]) -> list[StockMatch]:
        """DB 매칭 실패한 종목을 Haiku로 처리합니다."""
        if not self._claude:
            return []

        stocks_info = [{"name": s.name, "reason": s.reason} for s in stocks]
        prompt = f"""다음 종목/기업이 KOSPI/KOSDAQ 상장 종목 DB에서 찾을 수 없었습니다.
비상장 기업이라면 관련 상장사(지배주주·모회사·주요 관련사)로 대체해주세요.

검증 대상:
{json.dumps(stocks_info, ensure_ascii=False, indent=2)}

처리 규칙:
1. 비상장이지만 관련 상장사 있음 → 상장사명으로 대체 (이유에 관계 명시)
2. 외국 기업 → 관련 국내 상장사가 명확하면 포함, 없으면 제외
3. 관련 국내 상장사가 없으면 → 빈 배열에 포함하지 않음

반드시 JSON 배열로만 응답 (없으면 빈 배열 []):
[
  {{"name": "상장종목명", "reason": "관계 포함 이유 25자 이내"}},
  ...
]"""

        try:
            msg  = self._claude.messages.create(
                model=self._haiku_model,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )
            text = msg.content[0].text.strip()
            if "```" in text:
                parts = text.split("```")
                text  = parts[1] if len(parts) > 1 else text
                if text.lower().startswith("json"):
                    text = text[4:]
            if "[" in text:
                text = text[text.index("["):text.rindex("]") + 1]

            seen: set[str] = set()
            out:  list[StockMatch] = []
            for item in json.loads(text):
                if not isinstance(item, dict):
                    continue
                name = item.get("name", "").strip()
                if name and name not in seen:
                    seen.add(name)
                    out.append(StockMatch(name=name, reason=item.get("reason", "").strip()))
            return out
        except Exception as e:
            self._log.warning(f"AI 보조 오류: {e}")
            return []
