"""
AI 마켓 타임라인 - 데모 (목업 데이터)
API 키 없이 UI 미리보기용
"""

import json
import streamlit as st
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))

st.set_page_config(
    page_title="AI 마켓 타임라인 (데모)",
    page_icon="📈",
    layout="wide",
)

st.markdown("""
<style>
.theme-tag {
    display: inline-block;
    background: #EFF6FF;
    color: #1D4ED8;
    padding: 2px 10px;
    border-radius: 12px;
    margin: 2px 3px;
    font-size: 0.82rem;
    font-weight: 700;
    border: 1px solid #BFDBFE;
}
.stock-badge {
    display: inline-block;
    background: #F0FDF4;
    color: #15803D;
    padding: 3px 12px;
    border-radius: 14px;
    margin: 2px 3px;
    font-size: 0.85rem;
    font-weight: 600;
    text-decoration: none !important;
    border: 1px solid #86EFAC;
}
.stock-badge:hover { background: #DCFCE7; }
.summary-box {
    background: #F8FAFC;
    border-left: 4px solid #3B82F6;
    padding: 12px 16px;
    border-radius: 0 10px 10px 0;
    margin: 10px 0;
    font-size: 0.95rem;
    line-height: 1.7;
    color: #1E293B;
}
.top-theme-bar {
    background: linear-gradient(90deg, #EFF6FF 0%, #F0FDF4 100%);
    border-radius: 10px;
    padding: 10px 16px;
    margin-bottom: 16px;
    font-size: 0.95rem;
}
.hour-header { font-size: 1.05rem; font-weight: 700; color: #0F172A; }
.article-item {
    padding: 6px 0;
    border-bottom: 1px solid #F1F5F9;
    font-size: 0.9rem;
    line-height: 1.5;
}
.article-item:last-child { border-bottom: none; }
</style>
""", unsafe_allow_html=True)

# ── 목업 데이터 ──────────────────────────────────────────────

MOCK_TIMELINE = [
    {
        "hour_key": "2026-03-25 14:00",
        "theme_tags": "#반도체 #AI #엔비디아",
        "summary": "오후 2시, 엔비디아의 어닝 서프라이즈 발표 이후 국내 HBM 밸류체인 전반에 강한 매수세가 유입되고 있습니다. SK하이닉스와 한미반도체가 각각 4%, 6% 급등하며 장을 주도하고 있으며, 삼성전자도 동반 상승 중입니다. AI 서버 수요 급증에 따른 메모리 업황 개선 기대감이 반영된 것으로 분석됩니다.",
        "related_stocks": ["SK하이닉스", "한미반도체", "삼성전자", "DB하이텍"],
        "articles": [
            {"source": "한국경제", "title": "엔비디아 깜짝 실적에 HBM 관련주 급등", "link": "#"},
            {"source": "매일경제", "title": "SK하이닉스, HBM3E 공급 계약 확대 소식", "link": "#"},
            {"source": "조선비즈", "title": "AI 서버 투자 확대에 반도체 장비주도 강세", "link": "#"},
            {"source": "이데일리", "title": "삼성전자, 엔비디아향 HBM 퀄 테스트 통과 임박", "link": "#"},
        ]
    },
    {
        "hour_key": "2026-03-25 13:00",
        "theme_tags": "#로봇 #정책 #2차전지",
        "summary": "오후 1시, 정부의 첨단 로봇 산업 육성 정책 발표와 함께 레인보우로보틱스, 두산로보틱스 등 관련주가 일제히 상승했습니다. 한편 2차전지 섹터는 유럽 전기차 보조금 축소 우려로 LG에너지솔루션과 삼성SDI가 약보합세를 보이고 있습니다. 정책 모멘텀과 수급 변화에 따른 종목별 차별화 장세가 연출되고 있습니다.",
        "related_stocks": ["레인보우로보틱스", "두산로보틱스", "LG에너지솔루션", "삼성SDI"],
        "articles": [
            {"source": "파이낸셜뉴스", "title": "정부, 지능형 로봇 산업 5년간 3조 투자 계획 발표", "link": "#"},
            {"source": "헤럴드경제", "title": "레인보우로보틱스, 현대차와 협력 강화 MOU 체결", "link": "#"},
            {"source": "연합뉴스", "title": "유럽 전기차 판매량 1분기 예상치 하회", "link": "#"},
            {"source": "서울경제", "title": "LG에너지솔루션, 유럽 공장 가동률 조정 검토", "link": "#"},
        ]
    },
    {
        "hour_key": "2026-03-25 12:00",
        "theme_tags": "#바이오 #금리 #환율",
        "summary": "점심 시간대, 삼성바이오로직스의 대규모 수주 소식에 바이오 섹터 전반이 강세를 보였습니다. 미국 연준의 금리 동결 시사 발언 이후 원달러 환율이 1,320원대로 하락하며 수입 물가 부담 완화 기대감도 작용했습니다. 외국인 투자자 순매수 규모가 확대되며 코스피 지수를 지지하고 있는 모습입니다.",
        "related_stocks": ["삼성바이오로직스", "셀트리온", "한미약품", "유한양행"],
        "articles": [
            {"source": "이투데이", "title": "삼성바이오로직스, 글로벌 제약사 CMO 계약 1.2조 수주", "link": "#"},
            {"source": "매일경제", "title": "연준 파월 의장 '금리 동결 기조 유지' 발언", "link": "#"},
            {"source": "한국경제", "title": "원달러 환율 1,320원대 진입, 2개월 만에 최저", "link": "#"},
        ]
    },
    {
        "hour_key": "2026-03-25 11:00",
        "theme_tags": "#건설 #리츠 #부동산",
        "summary": "오전 11시, 정부의 주택 공급 확대 방안 발표에 건설주가 일제히 상승했으나 상승폭은 제한적입니다. 리츠 관련주는 금리 인하 기대감 재부각으로 배당 매력이 부각되며 소폭 상승세입니다. 전반적으로 거래량이 줄어든 가운데 업종 순환매 양상이 이어지고 있습니다.",
        "related_stocks": ["현대건설", "DL이앤씨", "삼성물산", "맥쿼리인프라"],
        "articles": [
            {"source": "조선비즈", "title": "정부, 3기 신도시 분양 일정 앞당긴다", "link": "#"},
            {"source": "서울경제", "title": "건설사 수주 잔고 역대 최대 수준 유지", "link": "#"},
            {"source": "이데일리", "title": "리츠 배당수익률 평균 6% 돌파, 투자 매력 상승", "link": "#"},
        ]
    },
]

def naver_stock_url(name):
    from urllib.parse import quote
    return f"https://search.naver.com/search.naver?query={quote(name)}+주가"

def render_theme_tags(tags_str):
    if not tags_str:
        return ""
    tags = [t for t in tags_str.strip().split() if t.startswith("#")]
    return " ".join(f'<span class="theme-tag">{t}</span>' for t in tags)

def render_stock_badges(stocks):
    if not stocks:
        return
    badges = " ".join([
        f'<a href="{naver_stock_url(s)}" target="_blank" class="stock-badge">📌 {s}</a>'
        for s in stocks
    ])
    st.markdown(
        f'<div style="margin:8px 0;"><strong>관련 종목</strong>&nbsp;&nbsp;{badges}</div>',
        unsafe_allow_html=True,
    )

# ── 사이드바 ─────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## ⚙️ 설정")
    hours_back = st.slider("조회 기간", 1, 24, 8, format="%d시간")
    all_sources = ["매일경제", "조선비즈", "파이낸셜뉴스", "헤럴드경제",
                   "한국경제", "이데일리", "이투데이", "연합뉴스", "서울경제"]
    selected_sources = st.multiselect("언론사 필터", all_sources, default=all_sources)
    search_query = st.text_input("🔍 키워드 검색", placeholder="예: 반도체, 금리...")
    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        st.button("🔄 새로고침", use_container_width=True)
    with col2:
        st.toggle("전체 자동 분석", value=False)
    st.caption(f"마지막 확인: {datetime.now(KST).strftime('%m/%d %H:%M')}")
    st.divider()
    st.markdown("""
**범례**
- 🔵 가장 최신 시간대
- ⚪ 이전 시간대
- 📌 종목 클릭 → 네이버 증권
- ▶️ 버튼 → AI 분석 생성
""")

# ── 헤더 ─────────────────────────────────────────────────────

left_col, right_col = st.columns([3, 1])
with left_col:
    st.markdown("# 📈 AI 마켓 타임라인")
with right_col:
    st.markdown(
        f"<div style='padding-top:18px;text-align:right;'>"
        f"🕒 <b>{datetime.now(KST).strftime('%Y.%m.%d %H:%M')}</b> 기준</div>",
        unsafe_allow_html=True,
    )

# 주도 테마 바
all_tags = "#반도체 #AI #로봇 #바이오 #2차전지 #엔비디아"
theme_badges = render_theme_tags(all_tags)
st.markdown(
    f'<div class="top-theme-bar">🔥 <strong>오늘 주도 테마</strong>&nbsp;&nbsp;{theme_badges}</div>',
    unsafe_allow_html=True,
)

# 통계
c1, c2, c3, c4 = st.columns(4)
c1.metric("총 기사", "47건")
c2.metric("시간대", "4개")
c3.metric("언론사", "9개")
c4.metric("AI 분석 완료", "4개 시간대")

st.divider()

# ── 타임라인 ─────────────────────────────────────────────────

for idx, item in enumerate(MOCK_TIMELINE):
    hour_key  = item["hour_key"]
    is_latest = (idx == 0)
    dot        = "🔵" if is_latest else "⚪"
    hour_label = hour_key[11:16]
    date_label = hour_key[:10]

    with st.container(border=True):
        # 헤더
        h_left, h_right = st.columns([7, 1])
        with h_left:
            theme_html = render_theme_tags(item["theme_tags"])
            st.markdown(
                f'<span class="hour-header">{dot} {date_label} '
                f'<span style="color:#2563EB;">{hour_label}</span></span>'
                f'&nbsp;&nbsp;{theme_html}',
                unsafe_allow_html=True,
            )
        with h_right:
            st.caption(f"📰 {len(item['articles'])}건")

        # AI 요약
        st.markdown(
            f'<div class="summary-box">🤖 {item["summary"]}</div>',
            unsafe_allow_html=True,
        )

        # 관련 종목
        render_stock_badges(item["related_stocks"])

        # 기사 목록
        with st.expander(f"📋 {hour_label} 기사 목록 ({len(item['articles'])}건) 펼치기"):
            for art in item["articles"]:
                st.markdown(
                    f'<div class="article-item">'
                    f'<span style="color:#64748B;font-size:0.8rem;">[{art["source"]}]</span> '
                    f'<a href="{art["link"]}" style="color:#1E293B;font-weight:500;">{art["title"]}</a>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

st.markdown("<br>", unsafe_allow_html=True)
