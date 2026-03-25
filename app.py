"""
AI 마켓 타임라인
=================
최근 24시간 뉴스를 시간대별로 그룹화하고
Claude AI가 섹터·헤드라인·요약·관련 종목을 분석합니다.
"""

import json
import anthropic
import streamlit as st
import pandas as pd
from supabase import create_client
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

KST       = timezone(timedelta(hours=9))
HOURS_BACK = 24

# ─────────────────────────────────────────────
# 페이지 설정
# ─────────────────────────────────────────────

st.set_page_config(
    page_title="AI 마켓 타임라인",
    page_icon="📈",
    layout="centered",
)

# ─────────────────────────────────────────────
# 글로벌 CSS
# ─────────────────────────────────────────────

st.markdown("""
<style>
/* 전체 배경 */
[data-testid="stAppViewContainer"] { background: #0f1117; }
[data-testid="stMain"]             { background: #0f1117; }

/* 헤더 바 */
.tl-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 4px 0 18px; border-bottom: 1px solid #1e2130; margin-bottom: 14px;
}
.tl-logo {
    font-size: 20px; font-weight: 800;
    background: linear-gradient(135deg, #4f9cf9, #a78bfa);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.tl-badge {
    font-size: 11px; background: #1e2130; border: 1px solid #2a2f45;
    color: #7c85a2; padding: 2px 9px; border-radius: 20px; margin-left: 8px;
    vertical-align: middle;
}
.tl-time { font-size: 12px; color: #7c85a2; }

/* 테마 바 */
.theme-bar {
    background: #0d0f1a; border: 1px solid #1e2130; border-radius: 10px;
    padding: 10px 16px; margin-bottom: 24px;
    display: flex; align-items: center; flex-wrap: wrap; gap: 6px;
}
.theme-label { font-size: 12px; color: #7c85a2; margin-right: 4px; }
.theme-tag {
    font-size: 12px; font-weight: 600; padding: 3px 10px;
    border-radius: 20px; cursor: default;
}
.tag-hot { background: rgba(239,68,68,0.15);  color: #f87171; border: 1px solid rgba(239,68,68,0.3); }
.tag-up  { background: rgba(34,197,94,0.12);  color: #4ade80; border: 1px solid rgba(34,197,94,0.25); }
.tag-neu { background: rgba(100,116,139,0.15); color: #94a3b8; border: 1px solid rgba(100,116,139,0.25); }

/* 날짜 구분 */
.date-sep {
    font-size: 12px; color: #4a5168; text-align: center;
    border-top: 1px solid #1e2130; padding-top: 10px; margin: 8px 0 20px;
}

/* 타임라인 카드 */
.tl-card {
    background: #13151f; border: 1px solid #1e2130; border-radius: 14px;
    padding: 16px 18px; margin-bottom: 6px; transition: border-color 0.2s;
}
.tl-card-active { border-color: #2a3a5c !important; }

/* 섹터 뱃지 */
.sector-badge {
    display: inline-flex; align-items: center; gap: 4px;
    font-size: 11px; font-weight: 700; padding: 3px 10px;
    border-radius: 6px; margin-bottom: 8px;
}
.s-semi   { background: rgba(59,130,246,0.12);  color: #60a5fa; border: 1px solid rgba(59,130,246,0.25); }
.s-robot  { background: rgba(139,92,246,0.15);  color: #a78bfa; border: 1px solid rgba(139,92,246,0.25); }
.s-battery{ background: rgba(234,179,8,0.12);   color: #fbbf24; border: 1px solid rgba(234,179,8,0.25); }
.s-bio    { background: rgba(16,185,129,0.12);  color: #34d399; border: 1px solid rgba(16,185,129,0.25); }
.s-fin    { background: rgba(245,158,11,0.12);  color: #fcd34d; border: 1px solid rgba(245,158,11,0.25); }
.s-etc    { background: rgba(100,116,139,0.12); color: #94a3b8; border: 1px solid rgba(100,116,139,0.25); }

/* 헤드라인 */
.card-headline { font-size: 15px; font-weight: 600; color: #dde1ef; line-height: 1.45; }
.card-source   { font-size: 11px; color: #4a5168; margin-top: 4px; }

/* AI 요약 박스 */
.ai-box {
    background: #0d0f1a; border: 1px solid #1a1f33; border-radius: 10px;
    padding: 12px 14px; margin: 12px 0 10px;
}
.ai-label { font-size: 11px; font-weight: 700; color: #4f9cf9; margin-bottom: 6px; }
.ai-text  { font-size: 13px; color: #9aa3bf; line-height: 1.7; }

/* 종목 칩 */
.stock-row { display: flex; flex-wrap: wrap; gap: 6px; margin: 10px 0 4px; }
.stock-chip {
    display: inline-flex; align-items: center; gap: 4px;
    font-size: 12px; font-weight: 600; padding: 5px 11px;
    border-radius: 8px; background: #1a1d2b; border: 1px solid #252a3d;
    color: #c8cfe8; transition: all 0.15s;
    position: relative; cursor: default;
}
.stock-chip:hover { background: #1f2540; border-color: #4f9cf9; color: #4f9cf9; }

/* 종목 툴팁 */
.stock-chip .tooltip {
    visibility: hidden; opacity: 0;
    background: #1e2540; color: #c8cfe8;
    border: 1px solid #3a4060; border-radius: 8px;
    padding: 6px 10px; font-size: 11px; font-weight: 400;
    white-space: nowrap; position: absolute;
    bottom: calc(100% + 6px); left: 50%;
    transform: translateX(-50%);
    z-index: 999; pointer-events: none;
    transition: opacity 0.15s;
    box-shadow: 0 4px 12px rgba(0,0,0,0.4);
}
.stock-chip .tooltip::after {
    content: ''; position: absolute; top: 100%; left: 50%;
    transform: translateX(-50%);
    border: 5px solid transparent;
    border-top-color: #3a4060;
}
.stock-chip:hover .tooltip { visibility: visible; opacity: 1; }

/* 기사 링크 */
.art-link {
    font-size: 13px; color: #4a5168; text-decoration: none !important;
    transition: color 0.15s;
}
.art-link:hover { color: #7c85a2; }
.art-source { font-size: 11px; color: #2a2f45; }

/* 빈 슬롯 */
.empty-slot { font-size: 12px; color: #252a3d; padding: 10px 0; }

/* 빈 상태 전체 */
.empty-state { text-align: center; padding: 60px 20px; }
.empty-icon  { font-size: 48px; opacity: 0.35; margin-bottom: 14px; }
.empty-title { font-size: 16px; font-weight: 600; color: #4a5168; margin-bottom: 8px; }
.empty-desc  { font-size: 13px; color: #2a2f45; line-height: 1.7; }

/* Streamlit 기본 여백 줄이기 */
.block-container { padding-top: 1.5rem !important; }
[data-testid="stExpander"] { background: #13151f; border: 1px solid #1e2130; border-radius: 10px; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# 연결 (캐시)
# ─────────────────────────────────────────────

@st.cache_resource
def get_supabase():
    return create_client(
        st.secrets["SUPABASE_URL"],
        st.secrets["SUPABASE_KEY"],
    )

@st.cache_resource
def get_claude():
    return anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])


# ─────────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_news() -> pd.DataFrame:
    client  = get_supabase()
    cutoff  = (datetime.now(KST) - timedelta(hours=HOURS_BACK)).strftime("%Y-%m-%d %H:%M")
    result  = (
        client.table("news_articles")
        .select("id, source, title, pubdate_kst, link, summary")
        .gte("pubdate_kst", cutoff)
        .order("pubdate_kst", desc=True)
        .limit(500)
        .execute()
    )
    return pd.DataFrame(result.data) if result.data else pd.DataFrame()


@st.cache_data(ttl=300)
def load_issues() -> dict:
    """timeline_issues 테이블 로드 → {hour: row} 딕셔너리"""
    client = get_supabase()
    cutoff = (datetime.now(KST) - timedelta(hours=HOURS_BACK)).strftime("%Y-%m-%d %H:%M")
    result = (
        client.table("timeline_issues")
        .select("*")
        .gte("hour", cutoff)
        .order("hour", desc=True)
        .execute()
    )
    return {row["hour"]: row for row in result.data} if result.data else {}


# ─────────────────────────────────────────────
# AI 분석
# ─────────────────────────────────────────────

def generate_analysis(hour: str, articles: list) -> dict:
    """해당 시간대 기사 목록 → Claude 분석 결과"""
    client    = get_claude()
    news_text = "\n".join(
        f"- [{a['source']}] {a['title']}" for a in articles[:30]
    )

    prompt = f"""다음은 {hour}에 수집된 국내 증권 뉴스 {len(articles)}건입니다.

반드시 아래 JSON 형식으로만 응답하세요 (설명 없이 JSON만):
{{
  "sector": "섹터명 1개 (반도체 / AI·로봇 / 2차전지 / 바이오 / 금융 / 에너지 / 자동차 / 유통 / 건설 중 택1 또는 직접 입력)",
  "headline": "이 시간대를 대표하는 주요 이슈 한 문장",
  "ai_summary": "투자자 관점의 핵심 흐름 요약 3~4문장. 구체적 수치·종목명 포함.",
  "stocks": ["종목명1", "종목명2", "종목명3"]
}}

작성 기준:
- sector: 가장 많이 언급된 섹터 1개
- headline: 40자 이내 명사형 문장
- ai_summary: 흐름·원인·영향 중심으로 서술, 2~4개 종목 자연스럽게 포함
- stocks: 뉴스에서 언급된 국내 상장 종목명만, 정확한 종목명으로 최대 5개

뉴스 목록:
{news_text}"""

    try:
        msg  = get_claude().messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        if "```" in text:
            parts = text.split("```")
            text  = parts[1] if len(parts) > 1 else text
            if text.lower().startswith("json"):
                text = text[4:]
        res = json.loads(text.strip())
        return {
            "sector":     res.get("sector",     "증권"),
            "headline":   res.get("headline",   "주요 이슈"),
            "ai_summary": res.get("ai_summary", ""),
            "stocks":     res.get("stocks",     []),
        }
    except Exception:
        return {
            "sector":     "증권",
            "headline":   "AI 분석 오류",
            "ai_summary": "분석 중 오류가 발생했습니다. 다시 시도해 주세요.",
            "stocks":     [],
        }


def save_analysis(hour: str, data: dict, articles: list):
    """분석 결과를 timeline_issues 테이블에 저장"""
    client   = get_supabase()
    sources  = list({a["source"] for a in articles})
    src_str  = " · ".join(sources[:3]) + (f" 외 {len(sources)-3}건" if len(sources) > 3 else "")

    client.table("timeline_issues").upsert(
        {
            "hour":          hour,
            "sector":        data["sector"],
            "headline":      data["headline"],
            "ai_summary":    data["ai_summary"],
            "stocks":        data["stocks"],
            "article_count": len(articles),
            "source_list":   src_str,
        },
        on_conflict="hour",
    ).execute()


# ─────────────────────────────────────────────
# UI 헬퍼
# ─────────────────────────────────────────────

SECTOR_STYLE = {
    "반도체":  ("💾", "s-semi"),
    "AI·로봇": ("🤖", "s-robot"),
    "로봇":    ("🤖", "s-robot"),
    "AI":      ("🤖", "s-robot"),
    "2차전지": ("🔋", "s-battery"),
    "배터리":  ("🔋", "s-battery"),
    "바이오":  ("💊", "s-bio"),
    "제약":    ("💊", "s-bio"),
    "금융":    ("🏦", "s-fin"),
    "은행":    ("🏦", "s-fin"),
}

def sector_html(sector: str) -> str:
    for key, (emoji, cls) in SECTOR_STYLE.items():
        if key in sector:
            return f'<span class="sector-badge {cls}">{emoji} {sector}</span>'
    return f'<span class="sector-badge s-etc">📊 {sector}</span>'


def stock_chips_html(stocks) -> str:
    """종목 목록 → 네이버 증권 링크 칩 + mouseover 툴팁 HTML
    stocks 형식: ["종목명"] 또는 [{"name":"종목명","reason":"이유"}]
    """
    if not stocks:
        return ""
    if isinstance(stocks, str):
        try:
            stocks = json.loads(stocks)
        except Exception:
            return ""

    chips = []
    for s in stocks:
        if isinstance(s, dict):
            name   = s.get("name",   "").strip()
            reason = s.get("reason", "").strip()
        else:
            name   = str(s).strip()
            reason = ""

        if not name:
            continue

        tooltip = f'<span class="tooltip">{reason}</span>' if reason else ""
        chips.append(
            f'<span class="stock-chip">'
            f'{name}{tooltip}'
            f'</span>'
        )

    return f'<div class="stock-row">{"".join(chips)}</div>'


def get_top_themes(issues: dict, n: int = 5) -> list:
    """전체 섹터에서 빈도순 top N 추출"""
    from collections import Counter
    sectors = [v.get("sector", "") for v in issues.values() if v.get("sector")]
    return [s for s, _ in Counter(sectors).most_common(n)]


# ─────────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────────

df     = load_news()
issues = load_issues()
now_kst = datetime.now(KST)


# ─────────────────────────────────────────────
# 헤더
# ─────────────────────────────────────────────

st.markdown(
    f"""
    <div class="tl-header">
      <div>
        <span class="tl-logo">📈 AI 마켓 타임라인</span>
        <span class="tl-badge">최근 24시간</span>
      </div>
      <span class="tl-time">🕒 {now_kst.strftime('%Y.%m.%d %H:%M')} 기준</span>
    </div>
    """,
    unsafe_allow_html=True,
)

# 새로고침 버튼
col_r, col_spacer = st.columns([1, 5])
with col_r:
    if st.button("🔄 새로고침", use_container_width=True):
        st.cache_data.clear()
        st.rerun()


# ─────────────────────────────────────────────
# 빈 상태
# ─────────────────────────────────────────────

if df.empty:
    st.markdown("""
    <div class="empty-state">
      <div class="empty-icon">📭</div>
      <div class="empty-title">아직 수집된 뉴스가 없습니다</div>
      <div class="empty-desc">
        GitHub Actions가 매시간 자동으로 뉴스를 수집합니다.<br>
        Actions → Stock News Collector → Run workflow 를 클릭해 수동으로 실행해보세요.
      </div>
    </div>
    """, unsafe_allow_html=True)
    st.stop()


# ─────────────────────────────────────────────
# 오늘 주도 테마 바
# ─────────────────────────────────────────────

if issues:
    top = get_top_themes(issues)
    if top:
        colors = ["tag-hot", "tag-hot", "tag-up", "tag-up", "tag-neu"]
        tags_html = "".join(
            f'<span class="theme-tag {colors[i]}">{s}</span>'
            for i, s in enumerate(top)
        )
        st.markdown(
            f'<div class="theme-bar"><span class="theme-label">🔥 오늘 주도 섹터</span>{tags_html}</div>',
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────
# 시간대별 타임라인
# ─────────────────────────────────────────────

df = df.copy()
df["hour"] = df["pubdate_kst"].str[:13] + ":00"
hours      = sorted(df["hour"].dropna().unique(), reverse=True)

prev_date = None

for idx, hour in enumerate(hours):

    hour_df   = df[df["hour"] == hour]
    articles  = hour_df.to_dict("records")
    is_latest = (idx == 0)
    issue     = issues.get(hour)

    # 날짜 구분선
    date_str = hour[:10]
    if date_str != prev_date:
        y, m, d = date_str.split("-")
        weekdays = ["월", "화", "수", "목", "금", "토", "일"]
        wd = weekdays[datetime(int(y), int(m), int(d)).weekday()]
        st.markdown(
            f'<div class="date-sep">{y}년 {int(m)}월 {int(d)}일 {wd}요일</div>',
            unsafe_allow_html=True,
        )
        prev_date = date_str

    hour_label = hour[11:16]   # "13:00"

    # ── 카드 ──────────────────────────────────
    card_cls = "tl-card tl-card-active" if is_latest else "tl-card"

    if issue:
        # 분석 완료 카드
        stocks_html = stock_chips_html(issue.get("stocks", []))
        src         = issue.get("source_list", "")
        cnt         = issue.get("article_count", len(articles))

        st.markdown(
            f"""
            <div class="{card_cls}">
              <div style="display:flex; align-items:flex-start; justify-content:space-between; gap:12px;">
                <div style="flex:1;">
                  {sector_html(issue.get("sector", "증권"))}
                  <div class="card-headline">{issue.get("headline", "")}</div>
                  <div class="card-source">{src}</div>
                </div>
                <span style="font-size:11px; color:#4a5168; background:#1a1d2b; padding:3px 8px;
                             border-radius:6px; white-space:nowrap;">📰 {cnt}건</span>
              </div>
              <div class="ai-box">
                <div class="ai-label">✦ AI 요약</div>
                <div class="ai-text">{issue.get("ai_summary", "")}</div>
              </div>
              {stocks_html}
              <div style="font-size:11px; color:#4a5168; margin-top:10px;">
                🕒 {hour_label}
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # 기사 목록 (접기/펼치기)
        with st.expander(f"📋 {hour_label} 기사 목록 ({len(articles)}건)"):
            for art in articles:
                title  = art.get("title",  "")
                link   = art.get("link",   "#")
                source = art.get("source", "")
                st.markdown(
                    f'<div style="padding:6px 0; border-bottom:1px solid #1e2130;">'
                    f'<span class="art-source">[{source}]</span> '
                    f'<a href="{link}" target="_blank" class="art-link">{title}</a>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    elif len(articles) == 0:
        # 빈 시간대
        st.markdown(
            f'<div class="tl-card"><span class="empty-slot">🕒 {hour_label} &nbsp;— 주요 이슈 없음</span></div>',
            unsafe_allow_html=True,
        )

    else:
        # 기사는 있으나 분석 미생성
        st.markdown(
            f"""
            <div class="{card_cls}">
              <div style="display:flex; align-items:center; justify-content:space-between;">
                <span style="font-size:14px; font-weight:600; color:#7c85a2;">🕒 {hour_label}</span>
                <span style="font-size:11px; color:#4a5168; background:#1a1d2b; padding:3px 8px;
                             border-radius:6px;">📰 {len(articles)}건 수집됨</span>
              </div>
              <div style="font-size:12px; color:#4a5168; margin-top:6px;">
                AI 분석이 아직 생성되지 않았습니다.
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if st.button(
            f"✦ {hour_label} AI 분석 생성",
            key=f"gen_{hour}",
            use_container_width=False,
            type="primary",
        ):
            with st.spinner(f"{hour_label} 뉴스 {len(articles)}건 분석 중..."):
                result = generate_analysis(hour, articles)
                save_analysis(hour, result, articles)
            st.cache_data.clear()
            st.rerun()

        # 기사 목록 미리보기
        with st.expander(f"📋 {hour_label} 기사 목록 ({len(articles)}건)"):
            for art in articles:
                title  = art.get("title",  "")
                link   = art.get("link",   "#")
                source = art.get("source", "")
                st.markdown(
                    f'<div style="padding:6px 0; border-bottom:1px solid #1e2130;">'
                    f'<span class="art-source">[{source}]</span> '
                    f'<a href="{link}" target="_blank" class="art-link">{title}</a>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

st.markdown("<br><br>", unsafe_allow_html=True)
