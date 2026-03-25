"""
증권 뉴스 AI 요약 대시보드
===========================
Streamlit 웹 앱 — Supabase에서 뉴스를 불러와 Claude AI로 요약합니다.

환경 변수 (Streamlit Cloud Secrets에 등록):
  SUPABASE_URL     : Supabase 프로젝트 URL
  SUPABASE_KEY     : Supabase anon key
  ANTHROPIC_API_KEY: Claude API 키
"""

import os
import anthropic
import streamlit as st
import pandas as pd
from supabase import create_client
from datetime import datetime, timezone, timedelta

# ──────────────────────────────────────────────
# 페이지 설정
# ──────────────────────────────────────────────

st.set_page_config(
    page_title="증권 뉴스 AI 요약",
    page_icon="📈",
    layout="wide",
)

KST = timezone(timedelta(hours=9))

# ──────────────────────────────────────────────
# 연결 (캐시)
# ──────────────────────────────────────────────

@st.cache_resource
def get_supabase():
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"],
    )

@st.cache_resource
def get_claude():
    return anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])


# ──────────────────────────────────────────────
# 데이터 로드
# ──────────────────────────────────────────────

@st.cache_data(ttl=300)  # 5분 캐시
def load_news(hours_back: int, sources: list[str]):
    client = get_supabase()
    cutoff = (datetime.now(KST) - timedelta(hours=hours_back)).strftime("%Y-%m-%d %H:%M")

    query = (
        client.table("news_articles")
        .select("id, collected_at, source, title, pubdate_kst, link, summary, ai_summary")
        .gte("pubdate_kst", cutoff)
        .order("pubdate_kst", desc=True)
        .limit(500)
    )

    if sources:
        query = query.in_("source", sources)

    result = query.execute()
    return pd.DataFrame(result.data) if result.data else pd.DataFrame()


# ──────────────────────────────────────────────
# AI 요약
# ──────────────────────────────────────────────

def ai_summarize_single(title: str, summary: str) -> str:
    """단일 기사 AI 요약"""
    client = get_claude()
    prompt = f"""다음 증권 뉴스 기사를 3줄 이내로 핵심만 요약해주세요.
투자자 관점에서 중요한 포인트를 강조해주세요.

제목: {title}
내용: {summary}

요약:"""
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def ai_summarize_bulk(articles: list[dict]) -> str:
    """여러 기사 종합 브리핑"""
    client = get_claude()
    news_text = "\n\n".join(
        f"[{a['source']}] {a['title']}\n{a.get('summary', '')}"
        for a in articles[:20]  # 최대 20건
    )
    prompt = f"""다음은 오늘의 증권 뉴스 목록입니다.
투자자를 위해 다음 형식으로 종합 브리핑을 작성해주세요:

1. 📊 오늘의 핵심 이슈 (3가지)
2. 📈 주목할 섹터/종목
3. ⚠️ 리스크 요인
4. 💡 투자 시사점

뉴스 목록:
{news_text}"""
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def save_ai_summary(article_id: int, ai_summary: str):
    """AI 요약 결과를 DB에 저장"""
    client = get_supabase()
    client.table("news_articles").update({"ai_summary": ai_summary}).eq("id", article_id).execute()


# ──────────────────────────────────────────────
# UI
# ──────────────────────────────────────────────

st.title("📈 증권 뉴스 AI 요약 대시보드")

# 사이드바 필터
with st.sidebar:
    st.header("🔍 필터")

    hours_back = st.slider("최근 몇 시간", min_value=1, max_value=48, value=6, step=1)

    all_sources = ["매일경제", "조선비즈", "파이낸셜뉴스", "헤럴드경제",
                   "한국경제", "이데일리", "이투데이", "연합뉴스", "서울경제"]
    selected_sources = st.multiselect("언론사 선택", all_sources, default=all_sources)

    search_query = st.text_input("제목 검색", placeholder="키워드 입력...")

    st.divider()
    if st.button("🔄 새로고침", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

    st.caption(f"마지막 업데이트: {datetime.now(KST).strftime('%H:%M')}")

# 데이터 로드
df = load_news(hours_back, selected_sources)

if df.empty:
    st.warning(f"최근 {hours_back}시간 이내 뉴스가 없습니다.")
    st.stop()

# 검색 필터
if search_query:
    df = df[df["title"].str.contains(search_query, case=False, na=False)]

# 상단 통계
col1, col2, col3, col4 = st.columns(4)
col1.metric("총 기사 수", f"{len(df)}건")
col2.metric("수집 언론사", f"{df['source'].nunique()}개")
col3.metric("AI 요약 완료", f"{df['ai_summary'].notna().sum()}건")
col4.metric("수집 기간", f"최근 {hours_back}시간")

st.divider()

# ── 종합 AI 브리핑 ─────────────────────────────
with st.expander("🤖 AI 종합 브리핑 생성", expanded=False):
    if st.button("📝 전체 뉴스 종합 브리핑 생성", type="primary"):
        articles = df[["source", "title", "summary"]].to_dict("records")
        with st.spinner("Claude AI가 분석 중입니다..."):
            briefing = ai_summarize_bulk(articles)
        st.markdown(briefing)

st.divider()

# ── 기사 목록 ──────────────────────────────────
st.subheader(f"📰 뉴스 목록 ({len(df)}건)")

# 언론사별 탭
tabs = st.tabs(["전체"] + sorted(df["source"].unique().tolist()))

def render_articles(articles_df):
    for _, row in articles_df.iterrows():
        with st.container(border=True):
            col_info, col_btn = st.columns([5, 1])

            with col_info:
                st.markdown(f"**[{row['source']}]** {row['title']}")
                st.caption(f"📅 {row['pubdate_kst']}  |  🔗 [기사 보기]({row['link']})")

                if row.get("summary"):
                    st.text(row["summary"][:150] + "..." if len(str(row["summary"])) > 150 else row["summary"])

                # AI 요약 표시
                if pd.notna(row.get("ai_summary")) and row["ai_summary"]:
                    st.info(f"🤖 **AI 요약:** {row['ai_summary']}")

            with col_btn:
                btn_key = f"summarize_{row['id']}"
                if st.button("AI 요약", key=btn_key, use_container_width=True):
                    with st.spinner("요약 중..."):
                        result = ai_summarize_single(row["title"], row.get("summary", ""))
                        save_ai_summary(row["id"], result)
                    st.success(result)
                    st.cache_data.clear()

# 전체 탭
with tabs[0]:
    render_articles(df)

# 언론사별 탭
for i, source in enumerate(sorted(df["source"].unique().tolist()), start=1):
    with tabs[i]:
        render_articles(df[df["source"] == source])
