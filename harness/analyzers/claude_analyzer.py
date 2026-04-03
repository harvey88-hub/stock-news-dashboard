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
        trace: AnalysisTrace | None = None
        try:
            recent_headlines = recent_headlines or []
            now_kst = datetime.now(_KST).strftime("%Y-%m-%d %H:%M:%S")

            # Step 0: 기사 사전 필터링 (Haiku)
            self._log.info("    [Step0] 기사 사전 필터링 중...")
            articles, removed_count = self._step0_filter_articles(hour, articles)

            # Step 1: 핵심 이슈 선정 + 관련 기사 추출 (Haiku)
            self._log.info("    [Step1] 핵심 이슈 선정 중...")
            issue_text, key_articles, no_issue_reason = self._step1_find_key_issue(hour, articles)

            trace = AnalysisTrace(
                hour=hour,
                created_at=now_kst,
                input_article_count=len(articles),
                input_articles=[{"source": a.source, "title": a.title} for a in articles[:30]],
                step1_issue=issue_text,
                step1_filtered_count=len(key_articles),
                issue_after_dedup=issue_text,
                issue_after_review=issue_text,
                step0_removed_count=removed_count,
            )

            # 주요 이슈가 없는 경우: trace에 사유 기록 후 조기 종료
            # (AI가 명시적 사유 없이 이슈를 선정하지 못한 폴백 포함)
            if not issue_text:
                trace.skipped = True
                trace.no_issue_reason = no_issue_reason or "Step1 이슈 미선정 (기사 부족 또는 응답 오류)"
                self._traces.append(trace)
                self._log.info(f"    ✗ 주요 이슈 없음: {trace.no_issue_reason}")
                return None

            # Step 1b: AI 유사도 검사 — 중복이면 최대 2회 재선정, 발전이면 태그 부여
            is_evo_issue = False
            evo_of = ""
            evo_type = ""
            if recent_headlines and issue_text:
                self._log.info("    [Step1b] AI 유사도/발전 검사 중...")
                trace.similarity_checked = True
                trace.compared_headlines = recent_headlines[:15]
                excluded: list[str] = []
                for attempt in range(2):
                    is_dup, similar_to, reason, is_evo, evolution_of, evolution_type = \
                        self._check_similarity_with_ai(issue_text, recent_headlines)
                    if is_evo and not is_dup:
                        # 발전 이슈: 중복 제거 없이 태그만 부여
                        is_evo_issue = True
                        evo_of = evolution_of
                        evo_type = evolution_type
                        self._log.info(
                            f"      발전 이슈 감지: [{evolution_type}] '{evolution_of}'"
                        )
                        break
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
                    new_issue, new_articles, _ = self._step1_find_key_issue(
                        hour, articles, excluded_topics=excluded
                    )
                    if new_issue:
                        issue_text, key_articles = new_issue, new_articles
                trace.issue_after_dedup = issue_text
                trace.is_evolution = is_evo_issue
                trace.evolution_of = evo_of
                trace.evolution_type = evo_type

            # Step 1c: 검토 Agent — 이슈 적절성 확인 및 수정
            self._log.info("    [Step1c] 이슈 적절성 검토 중...")
            issue_text, approved, feedback = self._review_agent(issue_text, key_articles)
            trace.review_approved = approved
            trace.review_feedback = feedback
            trace.issue_after_review = issue_text

            # Step 2: 심층 분석 (Sonnet)
            self._log.info("    [Step2] 심층 분석 중...")
            data = self._step2_deep_analysis(hour, key_articles, issue_hint=issue_text)

            # Step 2b: 팩트체크 — 시제·수치 정확성 검증 (Haiku)
            self._log.info("    [Step2b] 팩트체크 중...")
            headline_raw = data.get("headline", "")
            ai_summary_raw = data.get("ai_summary", "")
            headline_checked, ai_summary_checked, fc_passed, fc_corrections = self._factcheck_agent(
                headline_raw, ai_summary_raw, key_articles
            )
            data["headline"]   = headline_checked
            data["ai_summary"] = ai_summary_checked
            trace.headline_before_factcheck = headline_raw
            trace.factcheck_passed          = fc_passed
            trace.factcheck_corrections     = fc_corrections

            # Step 2c: ai_summary 품질 검토 (Haiku) → 미달 시 Sonnet 재생성
            self._log.info("    [Step2c] ai_summary 품질 검토 중...")
            final_summary, regenerated, quality_feedback = self._step2c_summary_quality_agent(
                data["ai_summary"], key_articles, issue_hint=issue_text
            )
            data["ai_summary"] = final_summary
            trace.summary_quality_passed = not regenerated
            trace.summary_regenerated    = regenerated
            trace.summary_quality_feedback = quality_feedback

            # 이슈 중요도 스코어링 (Haiku)
            self._log.info("    [Scoring] 이슈 중요도 스코어링 중...")
            sources_for_score = list({a.source for a in key_articles})
            impact_score, score_reason = self._scoring_agent(
                headline=data.get("headline", ""),
                ai_summary=data["ai_summary"],
                sector=data.get("sector", ""),
                article_count=len(key_articles),
                source_list=sources_for_score,
            )
            trace.impact_score        = impact_score
            trace.impact_score_reason = score_reason

            # 출처 정보 구성
            sources = list({a.source for a in articles})
            src_str = " · ".join(sources[:3]) + (
                f" 외 {len(sources)-3}건" if len(sources) > 3 else ""
            )

            result = AnalysisResult(
                hour=hour,
                sector=data.get("sector", "증권"),
                headline=data.get("headline", "주요 이슈"),
                ai_summary=data["ai_summary"],
                related_stocks=[
                    StockMatch(name=s.get("name", ""), reason=s.get("reason", ""))
                    for s in data.get("stocks", [])
                    if isinstance(s, dict) and s.get("name")
                ],
                article_count=len(articles),
                source_list=src_str,
                impact_score=impact_score,
                is_evolution=is_evo_issue,
                evolution_type=evo_type,
            )

            trace.final_headline = result.headline
            trace.final_sector   = result.sector
            self._traces.append(trace)

            self._log.info(f"    ✓ [{result.sector}] {result.headline}")
            return result

        except Exception as e:
            self._log.error(f"    시간대 {hour} 분석 실패: {e}")
            if trace is not None:
                trace.skipped = True
                trace.no_issue_reason = f"분석 오류: {str(e)[:60]}"
                self._traces.append(trace)
            return None

    def flush_traces(self) -> list[AnalysisTrace]:
        """수집된 추적 로그를 반환하고 내부 버퍼를 비웁니다."""
        traces, self._traces = self._traces, []
        return traces

    # ──────────────────────────────────────
    # Step 0 — 사전 필터링 Agent
    # ──────────────────────────────────────

    def _step0_filter_articles(
        self,
        hour: str,
        articles: list[Article],
    ) -> tuple[list[Article], int]:
        """Haiku로 분석 가치 없는 기사를 사전 필터링합니다.

        제거 대상: 광고성, 단순 IR 공시 반복, 낚시성 제목, 단순 시황 마감 정리

        Returns:
            (filtered_articles, removed_count)
        """
        if not articles:
            return articles, 0

        titles = "\n".join(
            f"{i}. [{a.source}] {a.title}" + (f" / {a.summary[:100]}" if a.summary else "")
            for i, a in enumerate(articles)
        )

        prompt = f"""{hour} 국내 증권 뉴스 {len(articles)}건입니다.
분석 가치가 없는 기사의 번호를 골라주세요.

제거 기준:
1. 광고성·홍보성 기사 (기업 PR, 협찬 기사, 광고 표시)
2. 단순 IR 공시 반복 (결산 공시, 정기 공시 단순 나열)
3. 낚시성 제목 (본문 내용과 무관한 자극적 제목)
4. 단순 시황 마감 정리 (코스피/코스닥 종가 나열, 상승률 순위 나열)
5. 동일 내용의 단순 재송·복제 기사

반드시 JSON 형식으로만 응답하세요:
{{
  "remove_indices": [제거할 기사 번호 목록],
  "reasons": ["번호: 제거 사유", ...]
}}

기사 목록:
{titles}"""

        try:
            msg = self._claude.messages.create(
                model=self._cfg.screening.model,
                max_tokens=400,
                messages=[{"role": "user", "content": prompt}],
            )
            text = self._extract_json_text(msg.content[0].text)
            res = json.loads(text)
            remove_indices = set(
                i for i in res.get("remove_indices", [])
                if isinstance(i, int) and 0 <= i < len(articles)
            )
            filtered = [a for i, a in enumerate(articles) if i not in remove_indices]
            removed_count = len(remove_indices)
            if removed_count:
                reasons = res.get("reasons", [])
                self._log.info(
                    f"      Step0 필터링: {removed_count}건 제거 "
                    f"({len(filtered)}건 남음)"
                )
                for r in reasons[:5]:
                    self._log.info(f"        - {r}")
            else:
                self._log.info(f"      Step0 필터링: 제거 없음 ({len(filtered)}건 유지)")
            return filtered, removed_count
        except Exception as e:
            self._log.warning(f"      Step0 필터링 오류: {e} → 원본 기사 유지")
            return articles, 0

    def _step1_find_key_issue(
        self,
        hour: str,
        articles: list[Article],
        excluded_topics: list[str] | None = None,
    ) -> tuple[str, list[Article], str]:
        """Haiku로 시간대 핵심 이슈 1개를 선정하고 (이슈 설명, 관련 기사, 이슈없음사유) 튜플을 반환합니다.

        주요 이슈가 없으면 issue는 빈 문자열, no_issue_reason에 사유를 반환합니다.
        """
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
  "issue": "핵심 이슈 한 줄 설명 (주요 이슈가 없으면 null)",
  "indices": [관련 기사 번호 목록],
  "no_issue_reason": "주요 이슈가 없는 경우 그 사유 20자 이내 (이슈가 있으면 null)"
}}

선정 기준:
- 가장 많은 언론사가 다루는 이슈
- 주가에 직접적인 영향을 줄 수 있는 이슈
- 단순 시황·마감 정리, 종목 나열, 개별 공시 등 시장 전체 영향이 없는 뉴스만 있으면 이슈 없음으로 처리{exclusion_section}
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
            issue_text = (res.get("issue") or "").strip()
            no_issue_reason = (res.get("no_issue_reason") or "").strip()
            indices = res.get("indices", [])
            selected = [articles[i] for i in indices if isinstance(i, int) and i < len(articles)]
            if selected and issue_text:
                self._log.info(f"      핵심 이슈: {issue_text} ({len(selected)}건 선별)")
                return issue_text, selected, ""
            if no_issue_reason:
                self._log.info(f"      주요 이슈 없음: {no_issue_reason}")
                return "", [], no_issue_reason
        except Exception as e:
            self._log.warning(f"      Step1 오류: {e} → 상위 5개로 대체")

        return "", articles[:5], ""

    def _check_similarity_with_ai(
        self,
        issue_text: str,
        recent_headlines: list[str],
    ) -> tuple[bool, str, str, bool, str, str]:
        """Haiku로 새 이슈가 최근 헤드라인과 의미상 유사/중복/발전인지 판단합니다.

        Returns:
            (is_duplicate, similar_to, reason, is_evolution, evolution_of, evolution_type)
            - is_duplicate:   단순 중복 여부
            - similar_to:     유사한 기존 헤드라인
            - reason:         판단 근거
            - is_evolution:   발전 이슈 여부 (중복이 아닌 의미 있는 후속)
            - evolution_of:   발전 대상 기존 헤드라인
            - evolution_type: "update" | "reversal" | "followup"
        """
        recent_list = "\n".join(f"- {h}" for h in recent_headlines[:15])
        prompt = f"""새로운 이슈가 최근 선정된 이슈들과 어떤 관계인지 판단하세요.

새로운 이슈: {issue_text}

최근 선정된 이슈들:
{recent_list}

판단 기준:
1. 단순 중복: 같은 기업·정책·사건이고 새로운 정보가 없으면 → is_duplicate: true
2. 발전(is_evolution): 같은 사건이지만 의미있는 진전이 있을 때
   - "update": 새로운 수치나 구체적 진전 사항이 추가됨
   - "reversal": 기존 방향과 반대 방향의 결과/결정이 나옴
   - "followup": 전일/전시간 이슈의 후속 조치, 반응, 영향 보도
3. 독립 이슈: 같은 기업이라도 전혀 다른 사건 → is_duplicate: false, is_evolution: false

반드시 JSON으로만 응답:
{{
  "is_duplicate": true/false,
  "similar_to": "유사한 기존 이슈 (없으면 null)",
  "reason": "판단 근거 20자 이내",
  "is_evolution": true/false,
  "evolution_of": "발전 대상 기존 이슈 (없으면 null)",
  "evolution_type": "update/reversal/followup 중 하나 (발전 아니면 null)"
}}"""

        try:
            msg = self._claude.messages.create(
                model=self._cfg.screening.model,
                max_tokens=250,
                messages=[{"role": "user", "content": prompt}],
            )
            text = self._extract_json_text(msg.content[0].text)
            res = json.loads(text)
            is_dup = bool(res.get("is_duplicate", False))
            similar_to = res.get("similar_to") or ""
            reason = res.get("reason", "")
            is_evo = bool(res.get("is_evolution", False))
            evolution_of = res.get("evolution_of") or ""
            evolution_type = res.get("evolution_type") or ""
            # 유효한 evolution_type 값만 허용
            if evolution_type not in ("update", "reversal", "followup"):
                evolution_type = ""
                is_evo = False

            if is_dup:
                self._log.info(f"      중복 판정: {reason} (기존: {similar_to})")
            elif is_evo:
                self._log.info(f"      발전 판정: [{evolution_type}] {evolution_of}")
            return is_dup, similar_to, reason, is_evo, evolution_of, evolution_type
        except Exception as e:
            self._log.warning(f"      유사도 검사 오류: {e} → 중복 아님으로 처리")
            return False, "", "", False, "", ""

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

    def _factcheck_agent(
        self,
        headline: str,
        ai_summary: str,
        articles: list[Article],
    ) -> tuple[str, str, bool, list[str]]:
        """Haiku로 Step2 생성 결과의 시제·수치 정확성을 검증합니다.

        Returns:
            (headline, ai_summary, passed, corrections)
            - passed: 수정 없이 통과하면 True
            - corrections: 수정된 항목 설명 목록
        """
        if not headline and not ai_summary:
            return headline, ai_summary, True, []

        articles_text = "\n".join(
            f"[기사 {i+1}] {a.title}" + (f" / {a.summary[:200]}" if a.summary else "")
            for i, a in enumerate(articles[:10])
        )

        prompt = f"""아래 [생성된 내용]이 [기사 원문]의 사실과 일치하는지 검토하세요.

[생성된 헤드라인]
{headline}

[생성된 요약]
{ai_summary}

[기사 원문]
{articles_text}

검토 항목:
1. 시제 표현 — 당일/전일/전월/전년/작년/올해 등이 기사 원문과 일치하는가
2. 수치 — 퍼센트, 금액, 배수 등이 기사 원문에 있는 값과 일치하는가
3. 방향성 — 급등/급락/상승/하락 방향이 기사 원문과 일치하는가
4. 주체 — 기업명, 국가명, 기관명이 기사 원문과 일치하는가

오류가 없으면 passed:true, revised_headline/revised_summary는 null로 반환하세요.
오류가 있으면 기사 원문 기준으로 수정하고 수정 내역을 corrections에 나열하세요.

반드시 JSON으로만 응답:
{{
  "passed": true/false,
  "revised_headline": "수정된 헤드라인 (오류 없으면 null)",
  "revised_summary": "수정된 요약 (오류 없으면 null)",
  "corrections": ["수정 내역 1", "수정 내역 2"]
}}"""

        try:
            msg = self._claude.messages.create(
                model=self._cfg.screening.model,
                max_tokens=600,
                messages=[{"role": "user", "content": prompt}],
            )
            text = self._extract_json_text(msg.content[0].text)
            res  = json.loads(text)

            passed       = bool(res.get("passed", True))
            corrections  = [c for c in res.get("corrections", []) if c]
            revised_hl   = (res.get("revised_headline") or "").strip()
            revised_sum  = (res.get("revised_summary")  or "").strip()

            if passed:
                self._log.info("      ✓ 팩트체크 통과")
                return headline, ai_summary, True, []
            else:
                final_hl  = revised_hl  or headline
                final_sum = revised_sum or ai_summary
                for c in corrections:
                    self._log.info(f"      ✎ 팩트체크 수정: {c}")
                return final_hl, final_sum, False, corrections

        except Exception as e:
            self._log.warning(f"      팩트체크 오류: {e} → 원본 유지")
            return headline, ai_summary, True, []

    def _step2c_summary_quality_agent(
        self,
        ai_summary: str,
        key_articles: list[Article],
        issue_hint: str = "",
    ) -> tuple[str, bool, str]:
        """Haiku로 ai_summary 품질을 검토하고, 미달 시 Sonnet으로 재생성합니다.

        검토 기준:
          1. "배경→시장영향→전망" 3단 구조
          2. 단순 제목 나열이 아닌 깊이있는 내용
          3. 3~4문장 분량

        Returns:
            (final_summary, regenerated, feedback)
        """
        if not ai_summary:
            return ai_summary, False, ""

        prompt = f"""아래 [AI 요약]이 투자자 관점 심층 요약으로서 품질 기준을 충족하는지 검토하세요.

[AI 요약]
{ai_summary}

품질 기준 (모두 충족해야 합니다):
1. 구조: "이슈 배경/원인" → "시장·종목 영향" → "향후 전망/주목 포인트" 3단 흐름이 있는가
2. 깊이: 단순히 기사 제목을 나열하지 않고 맥락과 의미를 설명하는가
3. 분량: 3~4문장 (너무 짧거나 너무 길지 않은가)

반드시 JSON으로만 응답:
{{
  "passed": true/false,
  "feedback": "검토 의견 40자 이내 (통과 시에도 작성)",
  "failed_criteria": [실패한 기준 번호 목록, 통과 시 빈 배열]
}}"""

        try:
            msg = self._claude.messages.create(
                model=self._cfg.screening.model,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )
            text = self._extract_json_text(msg.content[0].text)
            res = json.loads(text)
            passed = bool(res.get("passed", True))
            feedback = res.get("feedback", "")

            if passed:
                self._log.info(f"      ✓ 요약 품질 통과: {feedback}")
                return ai_summary, False, feedback

            # 품질 미달 → Sonnet으로 재생성 (1회)
            self._log.info(f"      ✎ 요약 품질 미달 ({feedback}) → Sonnet 재생성")
            articles_text = "\n".join(
                f"[기사 {i+1}] {a.title}" + (f" / {a.summary[:300]}" if a.summary else "")
                for i, a in enumerate(key_articles[:8])
            )
            regen_prompt = f"""아래 기사들을 바탕으로 투자자 관점 심층 요약을 다시 작성해주세요.

핵심 이슈: {issue_hint}

작성 기준:
1. 반드시 3~4문장으로 작성
2. 순서: ① 이슈 발생 배경/원인 → ② 시장 및 관련 종목 영향 → ③ 향후 전망/주목 포인트
3. 단순 제목 나열 금지, 맥락과 의미를 설명

기사:
{articles_text}

이전 요약의 문제점: {feedback}

요약만 출력하세요 (JSON 없이 텍스트로만):"""

            regen_msg = self._claude.messages.create(
                model=self._cfg.deep_analysis.model,
                max_tokens=400,
                messages=[{"role": "user", "content": regen_prompt}],
            )
            new_summary = regen_msg.content[0].text.strip()
            if new_summary:
                self._log.info("      ✓ 요약 재생성 완료")
                return new_summary, True, feedback
            return ai_summary, False, feedback

        except Exception as e:
            self._log.warning(f"      Step2c 오류: {e} → 원본 요약 유지")
            return ai_summary, False, ""

    def _scoring_agent(
        self,
        headline: str,
        ai_summary: str,
        sector: str,
        article_count: int,
        source_list: list[str],
    ) -> tuple[int, str]:
        """Haiku로 이슈 임팩트 점수(0~10)를 산출합니다.

        기준: 언론사 수, 정책/실적/테마 여부, 섹터 대표성, 주가 영향 예상 규모

        Returns:
            (score, reason)
        """
        if not headline:
            return 0, ""

        source_str = ", ".join(source_list[:10]) if source_list else "없음"
        prompt = f"""아래 이슈의 주식 시장 임팩트 점수를 0~10으로 산출하세요.

이슈 헤드라인: {headline}
섹터: {sector}
관련 기사 수: {article_count}건
보도 언론사: {source_str}

요약:
{ai_summary[:500]}

채점 기준:
- 언론사 수 (1개=+1, 3개=+2, 5개 이상=+3)
- 이슈 유형 (정책/규제=+3, 실적/가이던스=+2, 테마/이벤트=+1)
- 섹터 대표성 (시가총액 상위 섹터 이슈=+2)
- 주가 영향 예상 (즉각적 영향=+2, 중기 영향=+1)

반드시 JSON으로만 응답:
{{"score": 정수(0~10), "reason": "점수 산정 근거 40자 이내"}}"""

        try:
            msg = self._claude.messages.create(
                model=self._cfg.screening.model,
                max_tokens=150,
                messages=[{"role": "user", "content": prompt}],
            )
            text = self._extract_json_text(msg.content[0].text)
            res = json.loads(text)
            score = int(res.get("score", 0))
            score = max(0, min(10, score))   # 0~10 클램핑
            reason = res.get("reason", "")
            self._log.info(f"      임팩트 점수: {score}/10 ({reason})")
            return score, reason
        except Exception as e:
            self._log.warning(f"      스코어링 오류: {e} → 0점 처리")
            return 0, ""

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
