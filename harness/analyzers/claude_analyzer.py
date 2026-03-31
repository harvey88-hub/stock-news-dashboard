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
from datetime import datetime, timezone, timedelta

from core.config import AppConfig
from core.interfaces import Article, AnalysisResult, StockMatch, AnalysisTrace
from core.logging import get_logger
from core.errors import AnalyzerError

_KST = timezone(timedelta(hours=9))


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
        self._traces: list[AnalysisTrace] = []

    # ──────────────────────────────────────
    # 공개 메서드 (Analyzer 프로토콜)
    # ──────────────────────────────────────

    def analyze(
        self,
        articles: list[Article],
        analyzed_hours: set[str] | None = None,
        recent_headlines: list[str] | None = None,
        **kwargs,
    ) -> list[AnalysisResult]:
        """
        기사 목록을 시간대별로 그룹화하여 분석합니다.

        Args:
            articles:          분석할 기사 목록
            analyzed_hours:    이미 분석된 시간대 집합 (스킵 용)
            recent_headlines:  최근 선정된 이슈 헤드라인 목록 (중복 방지용)

        Returns:
            AnalysisResult 목록 (시간대별 1개)
        """
        if not articles:
            return []

        analyzed_hours   = analyzed_hours or set()
        recent_headlines = recent_headlines or []

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
        if recent_headlines:
            self._log.info(f"  최근 이슈 {len(recent_headlines)}개 중복 방지 적용")

        results: list[AnalysisResult] = []
        for i, hour in enumerate(pending):
            hour_articles = hour_map[hour]
            self._log.info(f"  [{i+1}/{len(pending)}] {hour} ({len(hour_articles)}건)")
            result = self._analyze_hour(hour, hour_articles, recent_headlines=recent_headlines)
            if result:
                results.append(result)
                # 현재 세션에서 새로 선정된 헤드라인도 이후 시간대에 반영
                recent_headlines = [result.headline] + recent_headlines
            if i < len(pending) - 1:
                time.sleep(2)  # API rate limit 방지

        return results

    # ──────────────────────────────────────
    # 시간대 분석
    # ──────────────────────────────────────

    def _analyze_hour(
        self,
        hour: str,
        articles: list[Article],
        recent_headlines: list[str] | None = None,
    ) -> AnalysisResult | None:
        """단일 시간대를 분석합니다."""
        try:
            recent_headlines = recent_headlines or []
            now_kst = datetime.now(_KST).strftime("%Y-%m-%d %H:%M:%S")

            # Step 1: 핵심 이슈 선정 + 관련 기사 추출 (Haiku)
            self._log.info("    [Step1] 핵심 이슈 선정 중...")
            issue_text, key_articles = self._step1_find_key_issue(hour, articles)

            trace = AnalysisTrace(
                hour=hour,
                created_at=now_kst,
                input_article_count=len(articles),
                input_articles=[{"source": a.source, "title": a.title} for a in articles[:30]],
                step1_issue=issue_text,
                step1_filtered_count=len(key_articles),
                issue_after_dedup=issue_text,
                issue_after_review=issue_text,
            )

            # Step 1b: AI 유사도 검사 — 중복이면 최대 2회 재선정
            if recent_headlines and issue_text:
                self._log.info("    [Step1b] AI 유사도 검사 중...")
                trace.similarity_checked = True
                trace.compared_headlines = recent_headlines[:15]
                excluded: list[str] = []
                for attempt in range(2):
                    is_dup, similar_to, reason = self._check_similarity_with_ai(
                        issue_text, recent_headlines
                    )
                    if not is_dup:
                        break
                    self._log.info(
                        f"      유사 이슈 감지: '{similar_to}' → 재선정 시도 {attempt + 1}/2"
                    )
                    trace.is_duplicate = True
                    trace.similar_to = similar_to
                    trace.similarity_reason = reason
                    trace.retry_count = attempt + 1
                    excluded.append(issue_text)
                    new_issue, new_articles = self._step1_find_key_issue(
                        hour, articles, excluded_topics=excluded
                    )
                    if new_issue:
                        issue_text, key_articles = new_issue, new_articles
                trace.issue_after_dedup = issue_text

            # Step 1c: 검토 Agent — 이슈 적절성 확인 및 수정
            self._log.info("    [Step1c] 이슈 적절성 검토 중...")
            issue_text, approved, feedback = self._review_agent(issue_text, key_articles)
            trace.review_approved = approved
            trace.review_feedback = feedback
            trace.issue_after_review = issue_text

            # Step 2: 심층 분석 (Sonnet)
            self._log.info("    [Step2] 심층 분석 중...")
            data = self._step2_deep_analysis(hour, key_articles, issue_hint=issue_text)

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

            trace.final_headline = result.headline
            trace.final_sector   = result.sector
            self._traces.append(trace)

            self._log.info(f"    ✓ [{result.sector}] {result.headline}")
            return result

        except Exception as e:
            self._log.error(f"    시간대 {hour} 분석 실패: {e}")
            return None

    def flush_traces(self) -> list[AnalysisTrace]:
        """수집된 추적 로그를 반환하고 내부 버퍼를 비웁니다."""
        traces, self._traces = self._traces, []
        return traces

    def _step1_find_key_issue(
        self,
        hour: str,
        articles: list[Article],
        excluded_topics: list[str] | None = None,
    ) -> tuple[str, list[Article]]:
        """Haiku로 시간대 핵심 이슈 1개를 선정하고 (이슈 설명, 관련 기사) 튜플을 반환합니다."""
        titles = "\n".join(
            f"{i}. [{a.source}] {a.title}"
            for i, a in enumerate(articles)
        )

        exclusion_section = ""
        if excluded_topics:
            items = "\n".join(f"- {t}" for t in excluded_topics)
            exclusion_section = f"\n\n[선정 제외 이슈 — 이미 검토 후 제외된 항목]\n{items}\n위 이슈는 선정하지 마세요.\n"

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
- 주가에 직접적인 영향을 줄 수 있는 이슈{exclusion_section}
기사 목록:
{titles}"""

        try:
            msg = self._claude.messages.create(
                model=self._cfg.screening.model,
                max_tokens=self._cfg.screening.max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            text = self._extract_json_text(msg.content[0].text)
            res = json.loads(text)
            issue_text = res.get("issue", "")
            indices = res.get("indices", [])
            selected = [articles[i] for i in indices if isinstance(i, int) and i < len(articles)]
            if selected and issue_text:
                self._log.info(f"      핵심 이슈: {issue_text} ({len(selected)}건 선별)")
                return issue_text, selected
        except Exception as e:
            self._log.warning(f"      Step1 오류: {e} → 상위 5개로 대체")

        return "", articles[:5]

    def _check_similarity_with_ai(
        self,
        issue_text: str,
        recent_headlines: list[str],
    ) -> tuple[bool, str, str]:
        """Haiku로 새 이슈가 최근 헤드라인과 의미상 유사한지 판단합니다.

        Returns:
            (is_duplicate, similar_to, reason): 중복 여부, 유사한 기존 헤드라인, 판단 근거
        """
        recent_list = "\n".join(f"- {h}" for h in recent_headlines[:15])
        prompt = f"""새로운 이슈가 최근 선정된 이슈들과 의미상 중복 또는 매우 유사한지 판단하세요.

새로운 이슈: {issue_text}

최근 선정된 이슈들:
{recent_list}

판단 기준:
- 같은 기업·정책·사건을 다루고 있으면 → 중복
- 같은 기업이라도 신제품 vs 실적 vs 인사 등 전혀 다른 사건이면 → 중복 아님
- 새로운 수치·진전·반전이 있는 후속 보도라면 → 중복 아님

반드시 JSON으로만 응답:
{{"is_duplicate": true/false, "similar_to": "유사한 기존 이슈 (없으면 null)", "reason": "판단 근거 20자 이내"}}"""

        try:
            msg = self._claude.messages.create(
                model=self._cfg.screening.model,
                max_tokens=150,
                messages=[{"role": "user", "content": prompt}],
            )
            text = self._extract_json_text(msg.content[0].text)
            res = json.loads(text)
            is_dup = bool(res.get("is_duplicate", False))
            similar_to = res.get("similar_to") or ""
            reason = res.get("reason", "")
            if is_dup:
                self._log.info(f"      유사 판정: {reason} (기존: {similar_to})")
            return is_dup, similar_to, reason
        except Exception as e:
            self._log.warning(f"      유사도 검사 오류: {e} → 중복 아님으로 처리")
            return False, "", ""

    def _review_agent(
        self,
        issue_text: str,
        articles: list[Article],
    ) -> tuple[str, bool, str]:
        """Haiku로 선정된 이슈의 적절성을 검토합니다.

        Returns:
            (final_issue, approved, feedback)
        """
        if not issue_text:
            return issue_text, True, ""

        titles = "\n".join(
            f"{i+1}. [{a.source}] {a.title}"
            for i, a in enumerate(articles[:10])
        )
        prompt = f"""선정된 핵심 이슈가 관련 기사들을 잘 대표하고 투자자에게 유의미한지 검토해주세요.

선정된 이슈: {issue_text}

관련 기사 ({len(articles)}건):
{titles}

검토 기준:
1. 기사 내용을 정확히 대표하는가?
2. 투자자 관점에서 실질적으로 중요한가?
3. 이슈 설명이 구체적이고 명확한가? (모호한 표현 지양)

반드시 JSON으로만 응답:
{{"approved": true/false, "revised_issue": "수정된 이슈 설명 40자 이내 (승인 시 null)", "feedback": "검토 의견 30자 이내"}}"""

        try:
            msg = self._claude.messages.create(
                model=self._cfg.screening.model,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            text = self._extract_json_text(msg.content[0].text)
            res = json.loads(text)
            approved = bool(res.get("approved", True))
            feedback = res.get("feedback", "")
            revised = (res.get("revised_issue") or "").strip()

            if approved:
                self._log.info(f"      ✓ 이슈 승인: {feedback}")
                return issue_text, True, feedback
            else:
                final = revised or issue_text
                self._log.info(f"      ✎ 이슈 수정: '{issue_text}' → '{final}' ({feedback})")
                return final, False, feedback
        except Exception as e:
            self._log.warning(f"      검토 Agent 오류: {e} → 원본 이슈 유지")
            return issue_text, True, ""

    def _step2_deep_analysis(
        self,
        hour: str,
        key_articles: list[Article],
        issue_hint: str = "",
    ) -> dict:
        """Sonnet으로 선별된 기사를 심층 분석합니다."""
        articles_text = ""
        for i, a in enumerate(key_articles, 1):
            summary = (a.summary or "").strip()
            articles_text += f"\n[기사 {i}] [{a.source}] {a.title}\n"
            if summary:
                articles_text += f"본문: {summary[:400]}\n"

        hint_line = f"\n핵심 이슈 (검토 완료): {issue_hint}\n" if issue_hint else ""
        prompt = f"""다음은 {hour}의 핵심 증권 뉴스입니다.{hint_line}기사 제목과 본문을 모두 참고하여 분석해주세요.

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
