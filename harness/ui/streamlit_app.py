"""
ui/streamlit_app.py
====================
Streamlit UI — Harness Store 인터페이스를 통해 데이터를 조회합니다.
기존 stock-news-dashboard/app.py에서 UI 렌더링 로직은 그대로 유지하면서
데이터 접근 방식만 Store 인터페이스로 교체했습니다.

실행:
    streamlit run ui/streamlit_app.py
"""

import sys
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta

import streamlit as st

# Harness 경로 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.harness import Harness

KST = timezone(timedelta(hours=9))

# ──────────────────────────────────────────
# Harness + Store 초기화 (5분 캐시)
# ──────────────────────────────────────────

@st.cache_resource
def get_store():
    """Store를 한 번만 초기화하고 캐시합니다."""
    harness = Harness.with_defaults()
    return harness.get_store()


@st.cache_data(ttl=300)
def load_analyses():
    store = get_store()
    return store.get_analyses(hours_back=24)


@st.cache_data(ttl=300)
def load_articles():
    store = get_store()
    return store.get_articles(hours_back=24)


# ──────────────────────────────────────────
# 페이지 설정
# ──────────────────────────────────────────

st.set_page_config(
    page_title="AI 마켓 타임라인",
    page_icon="📈",
    layout="centered",
)

# ──────────────────────────────────────────
# CSS (기존 스타일 유지)
# ──────────────────────────────────────────

st.markdown("""
<style>
[data-testid="stAppViewContainer"] { background: #0f1117; }
[data-testid="stMain"]             { background: #0f1117; }
[data-testid="stToolbar"]          { display: none !important; }
[data-testid="stHeader"]           { display: none !important; }
#MainMenu, footer, header          { display: none !important; }
.block-container { padding-top: 1.2rem !important; }

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
.empty-state { text-align: center; padding: 60px 20px; }
.empty-title { font-size: 16px; font-weight: 600; color: #4a5168; margin-bottom: 8px; }
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
# 데이터 로드
# ──────────────────────────────────────────

try:
    analyses = load_analyses()
except Exception as e:
    st.error(f"데이터 로드 실패: {e}")
    st.info("SUPABASE_URL, SUPABASE_KEY, ANTHROPIC_API_KEY 환경 변수를 확인하세요.")
    st.stop()

# ──────────────────────────────────────────
# 타임라인 렌더링
# ──────────────────────────────────────────

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
        stocks_html = ""
        for stock in result.related_stocks:
            tip = stock.reason if stock.reason else stock.name
            stocks_html += f'<span class="stock-chip" title="{tip}">{stock.name}</span>'

        st.markdown(f"""
        <div class="tl-card">
            <div class="sector-badge">{result.sector}</div>
            <div class="card-headline">{result.headline}</div>
            <div class="card-source">{result.hour} · {result.source_list}</div>
            <div class="ai-box">
                <div class="ai-label">🤖 AI 분석</div>
                <div class="ai-text">{result.ai_summary}</div>
            </div>
            <div class="stock-row">{stocks_html}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown(
        f'<div style="text-align:center;font-size:11px;color:#2a2f45;margin-top:20px;">'
        f'총 {len(analyses)}개 이슈 · 5분마다 자동 갱신</div>',
        unsafe_allow_html=True
    )
