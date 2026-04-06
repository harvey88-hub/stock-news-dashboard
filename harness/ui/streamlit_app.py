"""
ui/streamlit_app.py
====================
Streamlit UI — Harness Store 인터페이스를 통해 데이터를 조회합니다.

탭 구성:
  1. 📈 타임라인 — 시간대별 핵심 이슈 대시보드
  2. 📋 history  — AI 판단 전/후 과정 추적 로그

실행:
    streamlit run ui/streamlit_app.py
"""

import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.harness import Harness

KST = timezone(timedelta(hours=9))

# ──────────────────────────────────────────
# Store 초기화
# ──────────────────────────────────────────

@st.cache_resource
def get_store():
    harness = Harness.with_defaults()
    return harness.get_store()


@st.cache_data(ttl=300)
def load_analyses():
    return get_store().get_analyses(hours_back=48)


@st.cache_data(ttl=300)
def load_traces():
    return get_store().get_traces(hours_back=48)


# ──────────────────────────────────────────
# 페이지 설정
# ──────────────────────────────────────────

st.set_page_config(
    page_title="AI 마켓 타임라인",
    page_icon="📈",
    layout="centered",
)

# ──────────────────────────────────────────
# CSS
# ──────────────────────────────────────────

st.markdown("""
<style>
[data-testid="stAppViewContainer"] { background: #0f1117; }
[data-testid="stMain"]             { background: #0f1117; }
[data-testid="stToolbar"]          { display: none !important; }
[data-testid="stHeader"]           { display: none !important; }
#MainMenu, footer, header          { display: none !important; }
.block-container { padding-top: 1.2rem !important; }

/* 헤더 */
.tl-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 4px 0 16px; border-bottom: 1px solid #1e2130; margin-bottom: 16px;
}
.tl-logo {
    font-size: 18px; font-weight: 800;
    background: linear-gradient(135deg, #4f9cf9, #a78bfa);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.tl-time { font-size: 11px; color: #7c85a2; }

/* 타임라인 카드 */
.tl-card {
    background: #13151f; border: 1px solid #1e2130; border-radius: 14px;
    padding: 14px 16px; margin-bottom: 12px;
}
.sector-badge {
    display: inline-block; font-size: 11px; font-weight: 700;
    padding: 3px 9px; border-radius: 6px; margin-bottom: 7px;
    background: rgba(79,156,249,0.15); color: #60a5fa;
    border: 1px solid rgba(79,156,249,0.25);
}
.card-headline { font-size: 14px; font-weight: 600; color: #dde1ef; }
.card-source   { font-size: 11px; color: #4a5168; margin-top: 3px; }
.ai-box {
    background: #0d0f1a; border: 1px solid #1a1f33; border-radius: 10px;
    padding: 11px 13px; margin: 10px 0 9px;
}
.ai-label { font-size: 11px; font-weight: 700; color: #4f9cf9; margin-bottom: 5px; }
.ai-text  { font-size: 13px; color: #9aa3bf; line-height: 1.7; }
.stock-row { display: flex; flex-wrap: wrap; gap: 6px; margin: 9px 0 3px; }
.stock-chip {
    display: inline-flex; align-items: center;
    font-size: 12px; font-weight: 600; padding: 5px 11px;
    border-radius: 8px; background: #1a1d2b; border: 1px solid #252a3d; color: #c8cfe8;
}
.stock-chip-ai {
    display: inline-flex; align-items: center;
    font-size: 12px; font-weight: 600; padding: 5px 11px;
    border-radius: 8px; background: rgba(167,139,250,0.08); border: 1px solid rgba(167,139,250,0.3); color: #a78bfa;
}
.stock-group-label {
    font-size: 10px; font-weight: 700; color: #4a5168;
    margin-bottom: 4px; margin-top: 6px;
}

/* 빈 상태 */
.empty-state { text-align: center; padding: 60px 20px; }
.empty-title { font-size: 16px; font-weight: 600; color: #4a5168; margin-bottom: 8px; }

/* history 카드 */
.trace-card {
    background: #13151f; border: 1px solid #1e2130; border-radius: 14px;
    padding: 14px 16px; margin-bottom: 12px;
}
.trace-hour {
    font-size: 13px; font-weight: 700; color: #a0aec0; margin-bottom: 10px;
}
.trace-step {
    display: flex; align-items: flex-start; gap: 10px;
    padding: 8px 0; border-bottom: 1px solid #1a1f33;
    font-size: 12px;
}
.trace-step:last-child { border-bottom: none; }
.step-label {
    min-width: 72px; font-weight: 700; font-size: 11px;
    padding: 2px 7px; border-radius: 5px; text-align: center; margin-top: 1px;
    flex-shrink: 0;
}
.step-s0   { background: rgba(100,116,139,0.2);  color: #94a3b8; }
.step-s1   { background: rgba(79,156,249,0.15);  color: #60a5fa; }
.step-s1b  { background: rgba(167,139,250,0.15); color: #a78bfa; }
.step-s1c  { background: rgba(52,211,153,0.15);  color: #34d399; }
.step-s2   { background: rgba(251,191,36,0.15);  color: #fbbf24; }
.step-s2b  { background: rgba(251,146,60,0.15);  color: #fb923c; }
.step-s2c  { background: rgba(45,212,191,0.15);  color: #2dd4bf; }
.step-score{ background: rgba(244,114,182,0.15); color: #f472b6; }
.step-content { flex: 1; color: #9aa3bf; line-height: 1.6; min-width: 0; }
.step-issue { color: #dde1ef; font-weight: 600; }
.step-arrow { color: #4a5168; margin: 0 6px; }
.step-after { color: #60a5fa; font-weight: 600; }

/* 전/후 비교 박스 */
.diff-box {
    background: #0d0f1a; border: 1px solid #1a1f33; border-radius: 8px;
    padding: 8px 11px; margin-top: 6px; font-size: 11px; line-height: 1.6;
}
.diff-before { color: #6b7280; text-decoration: line-through; }
.diff-after  { color: #34d399; }

/* 배지 */
.badge-ok  {
    display: inline-block; font-size: 10px; font-weight: 700;
    padding: 1px 6px; border-radius: 4px;
    background: rgba(52,211,153,0.15); color: #34d399; border: 1px solid rgba(52,211,153,0.3);
}
.badge-warn {
    display: inline-block; font-size: 10px; font-weight: 700;
    padding: 1px 6px; border-radius: 4px;
    background: rgba(251,191,36,0.15); color: #fbbf24; border: 1px solid rgba(251,191,36,0.3);
}
.badge-edit {
    display: inline-block; font-size: 10px; font-weight: 700;
    padding: 1px 6px; border-radius: 4px;
    background: rgba(167,139,250,0.15); color: #a78bfa; border: 1px solid rgba(167,139,250,0.3);
}
.badge-skip {
    display: inline-block; font-size: 10px; font-weight: 700;
    padding: 1px 6px; border-radius: 4px;
    background: rgba(148,163,184,0.15); color: #94a3b8; border: 1px solid rgba(148,163,184,0.3);
}
.badge-zero {
    display: inline-block; font-size: 10px; font-weight: 700;
    padding: 1px 6px; border-radius: 4px;
    background: rgba(239,68,68,0.15); color: #f87171; border: 1px solid rgba(239,68,68,0.3);
}

/* 기사 목록 */
.articles-box {
    background: #0d0f1a; border: 1px solid #1a1f33; border-radius: 8px;
    padding: 8px 10px; margin-top: 6px; font-size: 11px; color: #4a5168;
    max-height: 140px; overflow-y: auto;
}
.article-row { padding: 2px 0; }
.article-src { color: #4f9cf9; font-weight: 600; margin-right: 4px; }

/* 필터링 사유 */
.filter-reason { color: #6b7280; font-size: 11px; padding: 1px 0; }
.filter-reason::before { content: "✕ "; color: #ef4444; }
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────
# 헤더
# ──────────────────────────────────────────

now_str = datetime.now(KST).strftime("%m/%d %H:%M KST")
st.markdown(f"""
<div class="tl-header">
    <div class="tl-logo">AI 마켓 타임라인</div>
    <div class="tl-time">{now_str}</div>
</div>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────
# 탭
# ──────────────────────────────────────────

tab_timeline, tab_history = st.tabs(["📈 타임라인", "📋 history"])

# ══════════════════════════════════════════
# 탭 1: 타임라인
# ══════════════════════════════════════════

with tab_timeline:
    try:
        analyses = load_analyses()
    except Exception as e:
        st.error(f"데이터 로드 실패: {e}")
        st.info("SUPABASE_URL, SUPABASE_KEY, ANTHROPIC_API_KEY 환경 변수를 확인하세요.")
        st.stop()

    if not analyses:
        st.markdown("""
        <div class="empty-state">
            <div class="empty-title">아직 분석된 뉴스가 없습니다</div>
            <div style="font-size:13px;color:#2a2f45;">
                파이프라인이 실행되면 여기에 표시됩니다.<br>
                <code>python cli.py pipeline hourly-news</code>
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        for result in analyses:
            article_stocks = [s for s in result.related_stocks if s.source != "ai"]
            ai_stocks      = [s for s in result.related_stocks if s.source == "ai"]

            article_chips = "".join(
                f'<span class="stock-chip" title="{s.reason or s.name}">{s.name}</span>'
                for s in article_stocks
            )
            ai_chips = "".join(
                f'<span class="stock-chip-ai" title="{s.reason or s.name}">✦ {s.name}</span>'
                for s in ai_stocks
            )

            stocks_block = ""
            if article_chips:
                stocks_block += f'<div class="stock-group-label">기사 언급</div><div class="stock-row">{article_chips}</div>'
            if ai_chips:
                stocks_block += f'<div class="stock-group-label">AI 관련주</div><div class="stock-row">{ai_chips}</div>'

            st.markdown(f"""
            <div class="tl-card">
                <div class="sector-badge">{result.sector}</div>
                <div class="card-headline">{result.headline}</div>
                <div class="card-source">{result.hour} · {result.source_list}</div>
                <div class="ai-box">
                    <div class="ai-label">🤖 AI 분석</div>
                    <div class="ai-text">{result.ai_summary}</div>
                </div>
                {stocks_block}
            </div>
            """, unsafe_allow_html=True)

        st.markdown(
            f'<div style="text-align:center;font-size:11px;color:#2a2f45;margin-top:20px;">'
            f'총 {len(analyses)}개 이슈 · 5분마다 자동 갱신</div>',
            unsafe_allow_html=True
        )

# ══════════════════════════════════════════
# 탭 2: history
# ══════════════════════════════════════════

with tab_history:
    try:
        traces = load_traces()
    except Exception as e:
        st.error(f"추적 로그 로드 실패: {e}")
        st.stop()

    if not traces:
        st.markdown("""
        <div class="empty-state">
            <div class="empty-title">추적 로그가 없습니다</div>
            <div style="font-size:13px;color:#2a2f45;">
                파이프라인 실행 후 여기에 AI 판단 과정이 기록됩니다.
            </div>
        </div>
        """, unsafe_allow_html=True)
    else:
        # ── 요약 지표 ────────────────────────────
        total       = len(traces)
        zero_count  = sum(1 for t in traces if t.no_issue_reason == "뉴스 수집: 0건")
        skip_count  = sum(1 for t in traces if t.skipped and t.no_issue_reason != "뉴스 수집: 0건")
        dup_count   = sum(1 for t in traces if t.is_duplicate)
        edit_count  = sum(1 for t in traces if not t.review_approved and not t.skipped)
        fc_count    = sum(1 for t in traces if not t.factcheck_passed)
        regen_count = sum(1 for t in traces if t.summary_regenerated)

        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("전체", total)
        m2.metric("0건 수집", zero_count,  help="뉴스 수집이 0건이었던 시간대")
        m3.metric("이슈 없음", skip_count, help="AI가 주요 이슈 없음으로 판단한 시간대")
        m4.metric("중복 감지", dup_count,  help="유사 이슈로 재선정된 횟수")
        m5.metric("이슈 수정", edit_count, help="검토 Agent가 이슈를 수정한 횟수")
        m6.metric("팩트수정", fc_count,    help="팩트체크에서 수정된 횟수")

        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

        # ── history 카드 ──────────────────────────
        for trace in traces:

            # 카드 헤더 배지
            badges = ""
            if trace.no_issue_reason == "뉴스 수집: 0건":
                badges = '<span class="badge-zero">✕ 0건 수집</span>'
            elif trace.skipped:
                badges = '<span class="badge-skip">— 이슈 없음</span>'
            else:
                if trace.is_duplicate:
                    badges += '<span class="badge-warn">⚠ 중복 재선정</span> '
                if not trace.review_approved:
                    badges += '<span class="badge-edit">✎ 이슈 수정</span> '
                if not trace.factcheck_passed:
                    badges += '<span class="badge-edit">✎ 팩트수정</span> '
                if trace.summary_regenerated:
                    badges += '<span class="badge-edit">✎ 요약재생성</span> '
                if not badges:
                    badges = '<span class="badge-ok">✓ 정상</span>'

            # ── 0건 수집 케이스 ────────────────────
            if trace.no_issue_reason == "뉴스 수집: 0건":
                st.markdown(f"""
                <div class="trace-card">
                    <div class="trace-hour">
                        {trace.hour}
                        <span style="font-weight:400;color:#4a5168;font-size:11px;margin-left:8px;">
                            {trace.created_at}
                        </span>
                        <span style="float:right">{badges}</span>
                    </div>
                    <div class="trace-step">
                        <span class="step-label step-s0">수집</span>
                        <div class="step-content">
                            <span style="color:#f87171;font-weight:600;">뉴스 수집: 0건</span>
                            <span style="color:#4a5168"> — 분석 중단</span>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                continue

            # ── Step 0: 사전 필터링 ────────────────
            total_before = trace.input_article_count
            filtered_count = total_before - trace.step0_removed_count
            if trace.step0_removed_count > 0:
                reasons_html = "".join(
                    f'<div class="filter-reason">{r}</div>'
                    for r in trace.step0_removal_reasons[:5]
                )
                s0_html = (
                    f'<span style="color:#4a5168">{total_before}건 입력</span>'
                    f'<span class="step-arrow">→</span>'
                    f'<span class="badge-warn">{trace.step0_removed_count}건 제거</span>'
                    f'<span style="color:#4a5168"> ({filtered_count}건 통과)</span>'
                    + (f'<div class="diff-box">{reasons_html}</div>' if reasons_html else "")
                )
            else:
                s0_html = (
                    f'<span style="color:#4a5168">{total_before}건 입력</span>'
                    f'<span class="step-arrow">→</span>'
                    f'<span class="badge-ok">전체 통과</span>'
                    f'<span style="color:#4a5168"> ({filtered_count}건)</span>'
                )

            # ── 이슈 없음 케이스 ───────────────────
            if trace.skipped:
                st.markdown(f"""
                <div class="trace-card">
                    <div class="trace-hour">
                        {trace.hour}
                        <span style="font-weight:400;color:#4a5168;font-size:11px;margin-left:8px;">
                            {trace.created_at}
                        </span>
                        <span style="float:right">{badges}</span>
                    </div>
                    <div class="trace-step">
                        <span class="step-label step-s0">Step 0</span>
                        <div class="step-content">{s0_html}</div>
                    </div>
                    <div class="trace-step">
                        <span class="step-label step-s1">Step 1</span>
                        <div class="step-content">
                            <span class="badge-skip">이슈 없음</span>
                            <span style="color:#e0a060;font-weight:500;margin-left:6px;">
                                {trace.no_issue_reason or "AI 판단: 주요 이슈 없음"}
                            </span>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                continue

            # ── Step 1: 핵심 이슈 선정 ────────────
            # 관련 뉴스 목록 (key_articles 우선, 없으면 input_articles 앞부분)
            key_arts = trace.step1_key_articles or trace.input_articles[:trace.step1_filtered_count]
            key_articles_rows = "".join(
                f'<div class="article-row">'
                f'<span class="article-src">[{a.get("source","")}]</span>'
                f'{a.get("title","")}'
                f'</div>'
                for a in key_arts[:15]
            )
            key_articles_block = (
                f'<div class="articles-box">{key_articles_rows}</div>'
                if key_articles_rows else ""
            )

            s1_html = (
                f'<span class="step-issue">{trace.step1_issue}</span>'
                f'<span style="color:#4a5168;margin-left:6px;">— 관련 기사 {trace.step1_filtered_count}건</span>'
                f'{key_articles_block}'
            )

            # ── Step 1b: 유사도 검사 ───────────────
            if trace.similarity_checked:
                if trace.is_duplicate:
                    s1b_before = trace.step1_issue
                    s1b_after  = trace.issue_after_dedup
                    diff_html = (
                        f'<div class="diff-box">'
                        f'<div class="diff-before">{s1b_before}</div>'
                        f'<div class="diff-after">→ {s1b_after}</div>'
                        f'</div>'
                    ) if s1b_before != s1b_after else ""
                    s1b_html = (
                        f'<span class="badge-warn">중복</span> '
                        f'<span style="color:#4a5168">유사: </span>'
                        f'<span class="step-issue">{trace.similar_to or "—"}</span>'
                        f'<span style="color:#4a5168"> / 사유: {trace.similarity_reason}'
                        f' / {trace.retry_count}회 재선정</span>'
                        f'{diff_html}'
                    )
                elif trace.is_evolution:
                    s1b_html = (
                        f'<span class="badge-edit">발전 이슈</span> '
                        f'<span style="color:#4a5168">유형: {trace.evolution_type} / 기존: </span>'
                        f'<span class="step-issue">{trace.evolution_of or "—"}</span>'
                    )
                else:
                    s1b_html = (
                        f'<span class="badge-ok">통과</span> '
                        f'<span style="color:#4a5168">'
                        f'{len(trace.compared_headlines)}개 최근 이슈와 비교 — 독립 이슈</span>'
                    )
            else:
                s1b_html = '<span style="color:#2a2f45">비교 대상 없음 (첫 실행)</span>'

            # ── Step 1c: 검토 Agent ────────────────
            if trace.review_approved:
                s1c_html = (
                    f'<span class="badge-ok">승인</span> '
                    f'<span style="color:#4a5168">{trace.review_feedback or "—"}</span>'
                )
            else:
                before_review = trace.issue_after_dedup or trace.step1_issue
                after_review  = trace.issue_after_review
                diff_html = (
                    f'<div class="diff-box">'
                    f'<div class="diff-before">{before_review}</div>'
                    f'<div class="diff-after">→ {after_review}</div>'
                    f'</div>'
                ) if before_review != after_review else ""
                s1c_html = (
                    f'<span class="badge-edit">수정</span> '
                    f'<span style="color:#4a5168">사유: {trace.review_feedback}</span>'
                    f'{diff_html}'
                )

            # ── Step 2: 심층 분석 결과 ─────────────
            s2_html = (
                f'<span style="color:#60a5fa;font-size:11px;">[{trace.final_sector}]</span> '
                f'<span class="step-issue">{trace.final_headline}</span>'
            )

            # ── Step 2b: 팩트체크 ──────────────────
            if trace.factcheck_passed:
                s2b_html = '<span class="badge-ok">통과</span> <span style="color:#4a5168">수정 없음</span>'
            else:
                corrections_html = "".join(
                    f'<div class="filter-reason" style="color:#fb923c;">{c}</div>'
                    for c in trace.factcheck_corrections[:5]
                )
                before_fc = trace.headline_before_factcheck
                after_fc  = trace.final_headline
                diff_html = ""
                if before_fc and before_fc != after_fc:
                    diff_html = (
                        f'<div class="diff-box">'
                        f'<div class="diff-before">{before_fc}</div>'
                        f'<div class="diff-after">→ {after_fc}</div>'
                        f'</div>'
                    )
                s2b_html = (
                    f'<span class="badge-edit">수정</span>'
                    + (f'<div class="diff-box" style="margin-top:4px;">{corrections_html}</div>' if corrections_html else "")
                    + diff_html
                )

            # ── Step 2c: 요약 품질 ─────────────────
            if trace.summary_quality_passed:
                s2c_html = (
                    f'<span class="badge-ok">통과</span> '
                    f'<span style="color:#4a5168">{trace.summary_quality_feedback or "—"}</span>'
                )
            else:
                feedback = trace.summary_quality_feedback or "—"
                regen_label = "재생성됨" if trace.summary_regenerated else "통과"
                badge = '<span class="badge-edit">재생성</span>' if trace.summary_regenerated else '<span class="badge-ok">통과</span>'
                s2c_html = (
                    f'{badge} '
                    f'<span style="color:#4a5168">미달 사유: {feedback}</span>'
                )

            # ── Scoring: 임팩트 점수 ───────────────
            score = trace.impact_score
            score_color = (
                "#f87171" if score >= 8 else
                "#fb923c" if score >= 6 else
                "#fbbf24" if score >= 4 else
                "#94a3b8"
            )
            scoring_html = (
                f'<span style="color:{score_color};font-weight:700;font-size:13px;">{score}</span>'
                f'<span style="color:#4a5168;font-size:11px;">/10</span>'
                + (f'<span style="color:#4a5168;margin-left:8px;">{trace.impact_score_reason}</span>' if trace.impact_score_reason else "")
            )

            st.markdown(f"""
            <div class="trace-card">
                <div class="trace-hour">
                    {trace.hour}
                    <span style="font-weight:400;color:#4a5168;font-size:11px;margin-left:8px;">
                        {trace.created_at}
                    </span>
                    <span style="float:right">{badges}</span>
                </div>
                <div class="trace-step">
                    <span class="step-label step-s0">Step 0</span>
                    <div class="step-content">
                        <span style="color:#4a5168">사전 필터링</span><br>
                        {s0_html}
                    </div>
                </div>
                <div class="trace-step">
                    <span class="step-label step-s1">Step 1</span>
                    <div class="step-content">
                        <span style="color:#4a5168">핵심 이슈 선정</span><br>
                        {s1_html}
                    </div>
                </div>
                <div class="trace-step">
                    <span class="step-label step-s1b">Step 1b</span>
                    <div class="step-content">
                        <span style="color:#4a5168">유사도 검사</span><br>
                        {s1b_html}
                    </div>
                </div>
                <div class="trace-step">
                    <span class="step-label step-s1c">Step 1c</span>
                    <div class="step-content">
                        <span style="color:#4a5168">검토 Agent</span><br>
                        {s1c_html}
                    </div>
                </div>
                <div class="trace-step">
                    <span class="step-label step-s2">Step 2</span>
                    <div class="step-content">
                        <span style="color:#4a5168">심층 분석</span><br>
                        {s2_html}
                    </div>
                </div>
                <div class="trace-step">
                    <span class="step-label step-s2b">Step 2b</span>
                    <div class="step-content">
                        <span style="color:#4a5168">팩트체크</span><br>
                        {s2b_html}
                    </div>
                </div>
                <div class="trace-step">
                    <span class="step-label step-s2c">Step 2c</span>
                    <div class="step-content">
                        <span style="color:#4a5168">요약 품질</span><br>
                        {s2c_html}
                    </div>
                </div>
                <div class="trace-step">
                    <span class="step-label step-score">점수</span>
                    <div class="step-content">
                        <span style="color:#4a5168">임팩트</span><br>
                        {scoring_html}
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown(
            f'<div style="text-align:center;font-size:11px;color:#2a2f45;margin-top:20px;">'
            f'{len(traces)}건 · 5분마다 자동 갱신</div>',
            unsafe_allow_html=True
        )
