"""
AI 자동 분석 스크립트
======================
GitHub Actions에서 rss_collector.py 실행 후 자동으로 실행됩니다.
최근 24시간 뉴스 중 AI 분석이 없는 시간대를 자동으로 분석하여
timeline_issues 테이블에 저장합니다.
"""

import os
import json
import time
import anthropic
from supabase import create_client
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

# ─────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────

KST        = timezone(timedelta(hours=9))
HOURS_BACK = 24
MODEL      = "claude-sonnet-4-5"  # Opus 대비 저렴하고 속도 빠름

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
claude   = anthropic.Anthropic(api_key=ANTHROPIC_KEY)


# ─────────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────────

def load_news() -> list:
    """최근 24시간 뉴스 로드"""
    cutoff = (datetime.now(KST) - timedelta(hours=HOURS_BACK)).strftime("%Y-%m-%d %H:%M")
    result = (
        supabase.table("news_articles")
        .select("id, source, title, pubdate_kst, link, summary")
        .gte("pubdate_kst", cutoff)
        .order("pubdate_kst", desc=True)
        .limit(500)
        .execute()
    )
    return result.data if result.data else []


def load_analyzed_hours() -> set:
    """이미 분석된 시간대 목록 로드"""
    cutoff = (datetime.now(KST) - timedelta(hours=HOURS_BACK)).strftime("%Y-%m-%d %H:%M")
    result = (
        supabase.table("timeline_issues")
        .select("hour")
        .gte("hour", cutoff)
        .execute()
    )
    return {row["hour"] for row in result.data} if result.data else set()


# ─────────────────────────────────────────────
# AI 분석
# ─────────────────────────────────────────────

def generate_analysis(hour: str, articles: list) -> dict:
    """해당 시간대 기사 목록 → Claude 분석"""
    news_text = "\n".join(
        f"- [{a['source']}] {a['title']}" for a in articles[:30]
    )

    prompt = f"""다음은 {hour}에 수집된 국내 증권 뉴스 {len(articles)}건입니다.

반드시 아래 JSON 형식으로만 응답하세요 (설명 없이 JSON만):
{{
  "sector": "섹터명 1개 (반도체 / AI·로봇 / 2차전지 / 바이오 / 금융 / 에너지 / 자동차 / 유통 / 건설 중 택1 또는 직접 입력)",
  "headline": "이 시간대를 대표하는 주요 이슈 한 문장 (40자 이내)",
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
        msg  = claude.messages.create(
            model=MODEL,
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()

        # 마크다운 코드블록 제거
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

    except Exception as e:
        print(f"  ⚠️  AI 분석 오류: {e}")
        return {
            "sector":     "증권",
            "headline":   "AI 분석 오류",
            "ai_summary": "분석 중 오류가 발생했습니다.",
            "stocks":     [],
        }


def save_analysis(hour: str, data: dict, articles: list):
    """분석 결과를 timeline_issues 테이블에 저장"""
    sources = list({a["source"] for a in articles})
    src_str = " · ".join(sources[:3]) + (f" 외 {len(sources)-3}건" if len(sources) > 3 else "")

    supabase.table("timeline_issues").upsert(
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
# 메인
# ─────────────────────────────────────────────

def main():
    print("=" * 50)
    print(f"AI 자동 분석 시작: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    print("=" * 50)

    # 뉴스 로드
    articles = load_news()
    if not articles:
        print("수집된 뉴스가 없습니다. 종료합니다.")
        return

    print(f"총 {len(articles)}건 뉴스 로드 완료")

    # 시간대별 그룹화
    from collections import defaultdict
    hour_map = defaultdict(list)
    for art in articles:
        if art.get("pubdate_kst"):
            hour_key = art["pubdate_kst"][:13] + ":00"
            hour_map[hour_key].append(art)

    print(f"시간대 {len(hour_map)}개 발견")

    # 이미 분석된 시간대 제외
    analyzed = load_analyzed_hours()
    pending  = sorted(
        [h for h in hour_map if h not in analyzed],
        reverse=True,
    )

    if not pending:
        print("모든 시간대가 이미 분석되었습니다. ✅")
        return

    print(f"미분석 시간대 {len(pending)}개 → AI 분석 시작\n")

    # 시간대별 AI 분석 실행
    for i, hour in enumerate(pending):
        hour_articles = hour_map[hour]
        print(f"[{i+1}/{len(pending)}] {hour} ({len(hour_articles)}건) 분석 중...")

        result = generate_analysis(hour, hour_articles)
        save_analysis(hour, result, hour_articles)

        print(f"  ✅ 섹터: {result['sector']} | 헤드라인: {result['headline'][:30]}...")
        print(f"  📌 종목: {', '.join(result['stocks'])}\n")

        # API 요청 간격 (rate limit 방지)
        if i < len(pending) - 1:
            time.sleep(1)

    print("=" * 50)
    print(f"분석 완료! {len(pending)}개 시간대 처리됨")
    print("=" * 50)


if __name__ == "__main__":
    main()
