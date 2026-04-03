"""
ui/streamlit_app.py
====================
Streamlit UI — Harness Store 인터페이스를 통해 데이터를 조회합니다.

탭 구성:
  1. 📈 타임라인 — 시간대별 핵심 이슈 대시보드
  2. 🔍 AI 판단 추적 — 각 단계에서 AI가 본 데이터와 내린 판단 로그

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
def load_analyses(hours_back: int = 24):
    return get_store().get_analyses(hours_back=hours_back)


@st.cache_data(ttl=300)
def load_traces(hours_back: int = 24):
    return get_store().get_traces(hours_back=hours_back)


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

/* 추적 뷰어 */
.trace-card {
    background: #13151f; border: 1px solid #1e2130; border-radius: 14px;
    padding: 14px 16px; margin-bottom: 12px;
}
.trace-hour {
    font-size: 13px; font-weight: 700; color: #a0aec0; margin-bottom: 10px;
}
.trace-step {
    display: flex; align-items: flex-start; gap: 10px;
    padding: 7px 0; border-bottom: 1px solid #1a1f33;
    font-size: 12px;
}
.trace-step:last-child { border-bottom: none; }
.step-label {
    min-width: 64px; font-weight: 700; font-size: 11px;
    padding: 2px 7px; border-radius: 5px; text-align: center; margin-top: 1px;
}
.step-s1  { background: rgba(79,156,249,0.15); color: #60a5fa; }
.step-s1b { background: rgba(167,139,250,0.15); color: #a78bfa; }
.step-s1c { background: rgba(52,211,153,0.15);  color: #34d399; }
.step-s2  { background: rgba(251,191,36,0.15);  color: #fbbf24; }
.step-content { flex: 1; color: #9aa3bf; line-height: 1.6; }
.step-issue { color: #dde1ef; font-weight: 600; }
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
.trace-articles {
    background: #0d0f1a; border: 1px solid #1a1f33; border-radius: 8px;
    padding: 8px 10px; margin-top: 6px; font-size: 11px; color: #4a5168;
    max-height: 120px; overflow-y: auto;
}
.trace-article-row { padding: 2px 0; }
.trace-article-src { color: #4f9cf9; font-weight: 600; margin-right: 4px; }
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

tab_timeline, tab_trace = st.tabs(["📈 타임라인", "🔍 AI 판단 추적"])

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
# 탭 2: AI 판단 추적
# ══════════════════════════════════════════

with tab_trace:
    # 조회 범위 선택
    col_range, col_refresh = st.columns([3, 1])
    with col_range:
        hours_back = st.select_slider(
            "조회 범위",
            options=[6, 12, 24, 48, 72],
            value=24,
            format_func=lambda h: f"최근 {h}시간",
            label_visibility="collapsed",
        )
    with col_refresh:
        if st.button("새로고침", use_container_width=True):
            st.cache_data.clear()

    try:
        traces = load_traces(hours_back=hours_back)
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
        total        = len(traces)
        skip_count   = sum(1 for t in traces if t.skipped)
        dup_count    = sum(1 for t in traces if t.is_duplicate)
        edit_count   = sum(1 for t in traces if not t.review_approved and not t.skipped)
        retry_total  = sum(t.retry_count for t in traces)

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("분석 시간대", total)
        m2.metric("이슈 없음", skip_count, help="AI가 주요 이슈 없음으로 판단한 시간대")
        m3.metric("중복 감지", dup_count, help="유사 이슈로 판정되어 재선정된 횟수")
        m4.metric("이슈 수정", edit_count, help="검토 Agent가 이슈를 수정한 횟수")
        m5.metric("총 재선정", retry_total, help="유사도 검사로 재시도된 총 횟수")

        st.markdown("<div style='height:12px'></div>", unsafe_allow_html=True)

        # ── 필터 ─────────────────────────────────
        filter_col1, filter_col2, filter_col3 = st.columns(3)
        with filter_col1:
            show_only_skip = st.checkbox("이슈 없음만", value=False)
        with filter_col2:
            show_only_dup = st.checkbox("중복 감지된 것만", value=False)
        with filter_col3:
            show_only_edit = st.checkbox("이슈 수정된 것만", value=False)

        filtered = traces
        if show_only_skip:
            filtered = [t for t in filtered if t.skipped]
        if show_only_dup:
            filtered = [t for t in filtered if t.is_duplicate]
        if show_only_edit:
            filtered = [t for t in filtered if not t.review_approved and not t.skipped]

        st.markdown(
            f'<div style="font-size:11px;color:#4a5168;margin-bottom:8px;">'
            f'{len(filtered)}건 표시 중</div>',
            unsafe_allow_html=True
        )

        # ── 트레이스 카드 ─────────────────────────
        for trace in filtered:
            # 카드 헤더: 이슈없음/중복/수정 여부 배지
            badges = ""
            if trace.skipped:
                badges += '<span class="badge-skip">— 이슈 없음</span> '
            if trace.is_duplicate:
                badges += '<span class="badge-warn">⚠ 중복 감지</span> '
            if not trace.review_approved and not trace.skipped:
                badges += '<span class="badge-edit">✎ 이슈 수정</span> '
            if not badges:
                badges = '<span class="badge-ok">✓ 정상</span>'

            # 입력 기사 목록 (접기)
            articles_rows = "".join(
                f'<div class="trace-article-row">'
                f'<span class="trace-article-src">[{a.get("source","")}]</span>'
                f'{a.get("title","")}'
                f'</div>'
                for a in trace.input_articles[:20]
            )
            articles_block = (
                f'<div class="trace-articles">{articles_rows}</div>'
                if articles_rows else ""
            )

            # 주요 이슈 없음 케이스: 간략 카드
            if trace.skipped:
                s1_html = (
                    f'<span class="badge-skip">이슈 없음</span> '
                    f'<span style="color:#e0a060;font-weight:500;">{trace.no_issue_reason or "AI 판단: 주요 이슈 없음"}</span>'
                    f'<br><span style="color:#4a5168">입력 기사 {trace.input_article_count}건 검토</span>'
                )
                st.markdown(f"""
                <div class="trace-card">
                    <div class="trace-hour">
                        {trace.hour}
                        <span style="font-weight:400;color:#4a5168;font-size:11px;margin-left:8px;">
                            분석: {trace.created_at}
                        </span>
                        <span style="float:right">{badges}</span>
                    </div>
                    <div class="trace-step">
                        <span class="step-label step-s1">Step 1</span>
                        <div class="step-content">
                            <span style="color:#4a5168">이슈 선정</span><br>
                            {s1_html}
                            {articles_block}
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                continue

            # Step 1: 이슈 선정
            s1_html = (
                f'<span class="step-issue">{trace.step1_issue}</span> '
                f'<span style="color:#4a5168">— 입력 {trace.input_article_count}건 중 '
                f'{trace.step1_filtered_count}건 선별</span>'
            )

            # Step 1b: 유사도 검사
            if trace.similarity_checked:
                if trace.is_duplicate:
                    s1b_html = (
                        f'<span class="badge-warn">중복</span> '
                        f'유사 이슈: <span class="step-issue">{trace.similar_to or "—"}</span>'
                        f'<br><span style="color:#4a5168">근거: {trace.similarity_reason} '
                        f'/ 재선정 {trace.retry_count}회 → '
                        f'<span class="step-issue">{trace.issue_after_dedup}</span></span>'
                    )
                else:
                    s1b_html = (
                        f'<span class="badge-ok">통과</span> '
                        f'<span style="color:#4a5168">'
                        f'{len(trace.compared_headlines)}개 최근 이슈와 비교</span>'
                    )
            else:
                s1b_html = '<span style="color:#2a2f45">비교 대상 없음 (첫 실행)</span>'

            # Step 1c: 검토 Agent
            if trace.review_approved:
                s1c_html = (
                    f'<span class="badge-ok">승인</span> '
                    f'<span style="color:#4a5168">{trace.review_feedback or "—"}</span>'
                )
            else:
                s1c_html = (
                    f'<span class="badge-edit">수정</span> '
                    f'<span class="step-issue">{trace.issue_after_review}</span>'
                    f'<br><span style="color:#4a5168">사유: {trace.review_feedback}</span>'
                )

            # Step 2: 최종 결과
            s2_html = (
                f'<span style="color:#60a5fa;font-size:11px;">[{trace.final_sector}]</span> '
                f'<span class="step-issue">{trace.final_headline}</span>'
            )

            st.markdown(f"""
            <div class="trace-card">
                <div class="trace-hour">
                    {trace.hour}
                    <span style="font-weight:400;color:#4a5168;font-size:11px;margin-left:8px;">
                        분석: {trace.created_at}
                    </span>
                    <span style="float:right">{badges}</span>
                </div>
                <div class="trace-step">
                    <span class="step-label step-s1">Step 1</span>
                    <div class="step-content">
                        <span style="color:#4a5168">이슈 선정</span><br>
                        {s1_html}
                        {articles_block}
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
                        <span style="color:#4a5168">최종 결과</span><br>
                        {s2_html}
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        st.markdown(
            f'<div style="text-align:center;font-size:11px;color:#2a2f45;margin-top:20px;">'
            f'{len(filtered)}건 · 5분마다 자동 갱신</div>',
            unsafe_allow_html=True
        )
