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

KST        = timezone(timedelta(hours=9))
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

/* Streamlit 상단 검은 띠 및 툴바 전체 숨기기 */
[data-testid="stToolbar"]      { display: none !important; }
[data-testid="stDecoration"]   { display: none !important; }
[data-testid="stStatusWidget"] { display: none !important; }
[data-testid="stHeader"]       { display: none !important; }
#MainMenu                      { display: none !important; }
footer                         { display: none !important; }
header                         { display: none !important; }

/* Streamlit 기본 여백 */
.block-container { padding-top: 1.2rem !important; padding-bottom: 2rem !important; }
[data-testid="stExpander"] { background: #13151f; border: 1px solid #1e2130 !important; border-radius: 10px; }

/* ── 헤더 ── */
.tl-header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 4px 0 16px; border-bottom: 1px solid #1e2130; margin-bottom: 16px;
}
.tl-logo {
    font-size: 18px; font-weight: 800;
    background: linear-gradient(135deg, #4f9cf9, #a78bfa);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.tl-badge {
    font-size: 10px; background: #1e2130; border: 1px solid #2a2f45;
    color: #7c85a2; padding: 2px 8px; border-radius: 20px; margin-left: 6px;
    vertical-align: middle;
}
.tl-time { font-size: 11px; color: #7c85a2; }

/* ── 하루 브리핑 ── */
.daily-brief {
    background: linear-gradient(135deg, #0d1020, #111428);
    border: 1px solid #2a3a5c; border-radius: 14px;
    padding: 16px 18px; margin-bottom: 24px;
}
.brief-header {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 12px; flex-wrap: wrap; gap: 4px;
}
.brief-title {
    font-size: 13px; font-weight: 700;
    background: linear-gradient(135deg, #4f9cf9, #a78bfa);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.brief-meta { font-size: 11px; color: #4a5168; }
.brief-item {
    display: flex; align-items: flex-start; gap: 8px;
    padding: 7px 0; border-bottom: 1px solid #1a1f33; line-height: 1.45;
}
.brief-item:last-child { border-bottom: none; padding-bottom: 0; }
.brief-time   { font-size: 11px; color: #4f9cf9; font-weight: 600;
                white-space: nowrap; padding-top: 1px; min-width: 36px; }
.brief-sector { font-size: 11px; color: #7c85a2; white-space: nowrap;
                padding-top: 1px; min-width: 48px; }
.brief-head   { font-size: 12px; color: #9aa3bf; }

/* ── 테마 바 ── */
.theme-bar {
    background: #0d0f1a; border: 1px solid #1e2130; border-radius: 10px;
    padding: 9px 14px; margin-bottom: 22px;
    display: flex; align-items: center; flex-wrap: wrap; gap: 6px;
}
.theme-label { font-size: 11px; color: #7c85a2; margin-right: 4px; }
.theme-tag {
    font-size: 11px; font-weight: 600; padding: 2px 9px;
    border-radius: 20px; cursor: default;
}
.tag-hot { background: rgba(239,68,68,0.15);  color: #f87171; border: 1px solid rgba(239,68,68,0.3); }
.tag-up  { background: rgba(34,197,94,0.12);  color: #4ade80; border: 1px solid rgba(34,197,94,0.25); }
.tag-neu { background: rgba(100,116,139,0.15); color: #94a3b8; border: 1px solid rgba(100,116,139,0.25); }

/* ── 날짜 구분 ── */
.date-sep {
    font-size: 11px; color: #4a5168; text-align: center;
    border-top: 1px solid #1e2130; padding-top: 10px; margin: 4px 0 18px;
}

/* ── 타임라인 ── */
.timeline-item {
    position: relative;
    padding-left: 22px;
    margin-bottom: 4px;
}
.timeline-item::before {
    content: '';
    position: absolute;
    left: 5px;
    top: 22px;
    bottom: -4px;
    width: 2px;
    background: linear-gradient(to bottom, #2a3a5c 60%, #1a1f2e);
}
.timeline-item:last-of-type::before { display: none; }
.timeline-dot {
    position: absolute;
    left: 0; top: 14px;
    width: 12px; height: 12px;
    border-radius: 50%;
    border: 2px solid #0f1117;
    z-index: 1;
}
.dot-active { background: #4f9cf9; box-shadow: 0 0 8px rgba(79,156,249,0.5); }
.dot-past   { background: #2a2f45; }

/* ── 타임라인 카드 ── */
.tl-card {
    background: #13151f; border: 1px solid #1e2130; border-radius: 14px;
    padding: 14px 16px; transition: border-color 0.2s;
}
.tl-card-active { border-color: #2a3a5c !important; }

/* ── 섹터 뱃지 ── */
.sector-badge {
    display: inline-flex; align-items: center; gap: 4px;
    font-size: 11px; font-weight: 700; padding: 3px 9px;
    border-radius: 6px; margin-bottom: 7px;
}
.s-semi    { background: rgba(59,130,246,0.12);  color: #60a5fa; border: 1px solid rgba(59,130,246,0.25); }
.s-robot   { background: rgba(139,92,246,0.15);  color: #a78bfa; border: 1px solid rgba(139,92,246,0.25); }
.s-battery { background: rgba(234,179,8,0.12);   color: #fbbf24; border: 1px solid rgba(234,179,8,0.25); }
.s-bio     { background: rgba(16,185,129,0.12);  color: #34d399; border: 1px solid rgba(16,185,129,0.25); }
.s-fin     { background: rgba(245,158,11,0.12);  color: #fcd34d; border: 1px solid rgba(245,158,11,0.25); }
.s-energy  { background: rgba(249,115,22,0.12);  color: #fb923c; border: 1px solid rgba(249,115,22,0.25); }
.s-etc     { background: rgba(100,116,139,0.12); color: #94a3b8; border: 1px solid rgba(100,116,139,0.25); }

/* ── 헤드라인 / 출처 ── */
.card-headline { font-size: 14px; font-weight: 600; color: #dde1ef; line-height: 1.45; }
.card-source   { font-size: 11px; color: #4a5168; margin-top: 3px; }

/* ── AI 요약 ── */
.ai-box {
    background: #0d0f1a; border: 1px solid #1a1f33; border-radius: 10px;
    padding: 11px 13px; margin: 10px 0 9px;
}
.ai-label { font-size: 11px; font-weight: 700; color: #4f9cf9; margin-bottom: 5px; }
.ai-text  { font-size: 13px; color: #9aa3bf; line-height: 1.7; }

/* ── 종목 칩 ── */
.stock-row { display: flex; flex-wrap: wrap; gap: 6px; margin: 9px 0 3px; }
.stock-chip {
    display: inline-flex; align-items: center;
    font-size: 12px; font-weight: 600; padding: 5px 11px;
    border-radius: 8px; background: #1a1d2b; border: 1px solid #252a3d;
    color: #c8cfe8; cursor: default;
    position: relative;
}
.stock-chip:hover { background: #1f2540; border-color: #4f9cf9; color: #4f9cf9; }

/* 툴팁 */
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
    border: 5px solid transparent; border-top-color: #3a4060;
}
.stock-chip:hover .tooltip { visibility: visible; opacity: 1; }

/* ── 기사 링크 ── */
.art-link   { font-size: 13px; color: #4a5168; text-decoration: none !important; }
.art-link:hover { color: #7c85a2; }
.art-source { font-size: 11px; color: #2a2f45; }

/* ── 빈 상태 ── */
.empty-state { text-align: center; padding: 60px 20px; }
.empty-icon  { font-size: 48px; opacity: 0.35; margin-bottom: 14px; }
.empty-title { font-size: 16px; font-weight: 600; color: #4a5168; margin-bottom: 8px; }
.empty-desc  { font-size: 13px; color: #2a2f45; line-height: 1.7; }

/* ══════════════════════════════════════
   모바일 최적화 (≤ 640px)
══════════════════════════════════════ */
@media (max-width: 640px) {
    .block-container { padding-left: 0.8rem !important; padding-right: 0.8rem !important; }

    .tl-logo  { font-size: 15px; }
    .tl-time  { font-size: 10px; }

    .daily-brief { padding: 13px 13px; }
    .brief-title { font-size: 12px; }
    .brief-head  { font-size: 11px; }

    .timeline-item { padding-left: 18px; }

    .tl-card { padding: 12px 13px; border-radius: 12px; }
    .card-headline { font-size: 13px; }
    .ai-text  { font-size: 12px; }

    .sector-badge { font-size: 10px; padding: 2px 7px; }

    .stock-chip { font-size: 11px; padding: 4px 9px; }
    /* 모바일에서 툴팁은 아래 방향으로 */
    .stock-chip .tooltip {
        bottom: auto; top: calc(100% + 6px);
        left: 0; transform: none;
        white-space: normal; max-width: 200px;
    }
    .stock-chip .tooltip::after {
        top: auto; bottom: 100%;
        border-top-color: transparent;
        border-bottom-color: #3a4060;
    }

    .brief-item  { gap: 5px; }
    .brief-time  { min-width: 32px; font-size: 10px; }
    .brief-sector{ min-width: 38px; font-size: 10px; }
}
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
    client = get_supabase()
    cutoff = (datetime.now(KST) - timedelta(hours=HOURS_BACK)).strftime("%Y-%m-%d %H:%M")
    result = (
        client.table("news_articles")
        .select("id, source, title, pubdate_kst, collected_at, link, summary")
        .gte("collected_at", cutoff)
        .order("collected_at", desc=True)
        .limit(500)
        .execute()
    )
    return pd.DataFrame(result.data) if result.data else pd.DataFrame()


@st.cache_data(ttl=300)
def load_issues() -> dict:
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
# AI 분석 (수동 버튼용)
# ─────────────────────────────────────────────

def generate_analysis(hour: str, articles: list) -> dict:
    news_text = "\n".join(
        f"- [{a['source']}] {a['title']}" for a in articles[:30]
    )
    prompt = f"""다음은 {hour}에 수집된 국내 증권 뉴스 {len(articles)}건입니다.

반드시 아래 JSON 형식으로만 응답하세요 (설명 없이 JSON만):
{{
  "sector": "섹터명 1개 (반도체 / AI·로봇 / 2차전지 / 바이오 / 금융 / 에너지 / 자동차 / 유통 / 건설 중 택1)",
  "headline": "이 시간대를 대표하는 주요 이슈 한 문장 (40자 이내)",
  "ai_summary": "투자자 관점의 핵심 흐름 요약 3~4문장.",
  "stocks": [{{"name": "종목명", "reason": "관련 이유 20자 이내"}}]
}}

뉴스 목록:
{news_text}"""

    try:
        msg  = get_claude().messages.create(
            model="claude-sonnet-4-5",
            max_tokens=700,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()
        if "```" in text:
            parts = text.split("```")
            text  = parts[1] if len(parts) > 1 else text
            if text.lower().startswith("json"):
                text = text[4:]
        res = json.loads(text.strip())
        raw = res.get("stocks", [])
        stocks = []
        for s in raw:
            if isinstance(s, dict) and s.get("name"):
                stocks.append({"name": s["name"].strip(), "reason": s.get("reason","").strip()})
            elif isinstance(s, str):
                stocks.append({"name": s.strip(), "reason": ""})
        return {
            "sector":     res.get("sector",     "증권"),
            "headline":   res.get("headline",   "주요 이슈"),
            "ai_summary": res.get("ai_summary", ""),
            "stocks":     stocks,
        }
    except Exception:
        return {"sector":"증권","headline":"AI 분석 오류","ai_summary":"분석 중 오류가 발생했습니다.","stocks":[]}


def save_analysis(hour: str, data: dict, articles: list):
    client  = get_supabase()
    sources = list({a["source"] for a in articles})
    src_str = " · ".join(sources[:3]) + (f" 외 {len(sources)-3}건" if len(sources) > 3 else "")
    client.table("timeline_issues").upsert(
        {"hour": hour, "sector": data["sector"], "headline": data["headline"],
         "ai_summary": data["ai_summary"], "stocks": data["stocks"],
         "article_count": len(articles), "source_list": src_str},
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
    "에너지":  ("⚡", "s-energy"),
    "정유":    ("⚡", "s-energy"),
}

def sector_html(sector: str) -> str:
    for key, (emoji, cls) in SECTOR_STYLE.items():
        if key in sector:
            return f'<span class="sector-badge {cls}">{emoji} {sector}</span>'
    return f'<span class="sector-badge s-etc">📊 {sector}</span>'


def stock_chips_html(stocks) -> str:
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
        chips.append(f'<span class="stock-chip">{name}{tooltip}</span>')
    return f'<div class="stock-row">{"".join(chips)}</div>'


def get_top_themes(issues: dict, n: int = 5) -> list:
    from collections import Counter
    sectors = [v.get("sector", "") for v in issues.values() if v.get("sector")]
    return [s for s, _ in Counter(sectors).most_common(n)]


# ─────────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────────

df      = load_news()
issues  = load_issues()
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
# 하루 브리핑
# ─────────────────────────────────────────────

if issues:
    today     = now_kst.strftime("%Y-%m-%d")
    today_iss = sorted(
        [(h, v) for h, v in issues.items() if h.startswith(today)],
        key=lambda x: x[0], reverse=True
    )
    if today_iss:
        count      = len(today_iss)
        sectors    = list(dict.fromkeys(
            [v.get("sector","") for _,v in today_iss if v.get("sector")]
        ))[:4]
        sector_str = " · ".join(sectors)

        items_html = ""
        for hour, issue in today_iss[:6]:
            h        = hour[11:16]
            sector   = issue.get("sector",   "")
            headline = issue.get("headline", "")
            items_html += (
                f'<div class="brief-item">'
                f'<span class="brief-time">{h}</span>'
                f'<span class="brief-sector">[{sector}]</span>'
                f'<span class="brief-head">{headline}</span>'
                f'</div>'
            )

        st.markdown(
            f"""
            <div class="daily-brief">
              <div class="brief-header">
                <span class="brief-title">📋 오늘의 AI 마켓 브리핑</span>
                <span class="brief-meta">{now_kst.strftime('%Y.%m.%d')} · {count}건 분석 · {sector_str}</span>
              </div>
              {items_html}
            </div>
            """,
            unsafe_allow_html=True,
        )


# ─────────────────────────────────────────────
# 오늘 주도 테마 바
# ─────────────────────────────────────────────

if issues:
    top = get_top_themes(issues)
    if top:
        colors    = ["tag-hot", "tag-hot", "tag-up", "tag-up", "tag-neu"]
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

df       = df.copy()
df["hour"] = df["collected_at"].str[:13] + ":00"
hours    = sorted(df["hour"].dropna().unique(), reverse=True)

prev_date  = None
total_hours = len(hours)

for idx, hour in enumerate(hours):

    hour_df  = df[df["hour"] == hour]
    articles = hour_df.to_dict("records")
    is_last  = (idx == total_hours - 1)
    is_latest = (idx == 0)
    issue    = issues.get(hour)

    # 날짜 구분선
    date_str = hour[:10]
    if date_str != prev_date:
        y, m, d = date_str.split("-")
        weekdays = ["월","화","수","목","금","토","일"]
        wd = weekdays[datetime(int(y), int(m), int(d)).weekday()]
        st.markdown(
            f'<div class="date-sep">{y}년 {int(m)}월 {int(d)}일 {wd}요일</div>',
            unsafe_allow_html=True,
        )
        prev_date = date_str

    hour_label = hour[11:16]
    card_cls   = "tl-card tl-card-active" if is_latest else "tl-card"
    dot_cls    = "dot-active" if is_latest else "dot-past"
    line_style = "display:none;" if is_last else ""

    # ── 분석 완료 카드 ──
    if issue:
        stocks_html = stock_chips_html(issue.get("stocks", []))
        src  = issue.get("source_list", "")
        cnt  = issue.get("article_count", len(articles))

        st.markdown(
            f"""
            <div class="timeline-item">
              <div class="timeline-dot {dot_cls}"></div>
              <div style="position:absolute;left:5px;top:26px;bottom:-4px;
                          width:2px;background:linear-gradient(to bottom,#2a3a5c,#1a1f2e);
                          {line_style}"></div>
              <div class="{card_cls}">
                <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:10px;">
                  <div style="flex:1;">
                    {sector_html(issue.get("sector","증권"))}
                    <div class="card-headline">{issue.get("headline","")}</div>
                    <div class="card-source">{src}</div>
                  </div>
                  <span style="font-size:11px;color:#4a5168;background:#1a1d2b;
                               padding:3px 8px;border-radius:6px;white-space:nowrap;">
                    📰 {cnt}건
                  </span>
                </div>
                <div class="ai-box">
                  <div class="ai-label">✦ AI 요약</div>
                  <div class="ai-text">{issue.get("ai_summary","")}</div>
                </div>
                {stocks_html}
                <div style="font-size:11px;color:#4a5168;margin-top:9px;">🕒 {hour_label}</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.expander(f"📋 {hour_label} 기사 목록 ({len(articles)}건)"):
            for art in articles:
                st.markdown(
                    f'<div style="padding:6px 0;border-bottom:1px solid #1e2130;">'
                    f'<span class="art-source">[{art.get("source","")}]</span> '
                    f'<a href="{art.get("link","#")}" target="_blank" class="art-link">{art.get("title","")}</a>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    # ── 기사는 있으나 미분석 ──
    elif len(articles) > 0:
        st.markdown(
            f"""
            <div class="timeline-item">
              <div class="timeline-dot {dot_cls}"></div>
              <div style="position:absolute;left:5px;top:26px;bottom:-4px;
                          width:2px;background:linear-gradient(to bottom,#2a3a5c,#1a1f2e);
                          {line_style}"></div>
              <div class="{card_cls}">
                <div style="display:flex;align-items:center;justify-content:space-between;">
                  <span style="font-size:13px;font-weight:600;color:#7c85a2;">🕒 {hour_label}</span>
                  <span style="font-size:11px;color:#4a5168;background:#1a1d2b;
                               padding:3px 8px;border-radius:6px;">📰 {len(articles)}건 수집됨</span>
                </div>
                <div style="font-size:12px;color:#4a5168;margin-top:6px;">
                  AI 분석이 아직 생성되지 않았습니다.
                </div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if st.button(
            f"✦ {hour_label} AI 분석 생성",
            key=f"gen_{hour}_{idx}",
            use_container_width=False,
            type="primary",
        ):
            with st.spinner(f"{hour_label} 뉴스 {len(articles)}건 분석 중..."):
                result = generate_analysis(hour, articles)
                save_analysis(hour, result, articles)
            st.cache_data.clear()
            st.rerun()

        with st.expander(f"📋 {hour_label} 기사 목록 ({len(articles)}건)"):
            for art in articles:
                st.markdown(
                    f'<div style="padding:6px 0;border-bottom:1px solid #1e2130;">'
                    f'<span class="art-source">[{art.get("source","")}]</span> '
                    f'<a href="{art.get("link","#")}" target="_blank" class="art-link">{art.get("title","")}</a>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

st.markdown("<br><br>", unsafe_allow_html=True)
