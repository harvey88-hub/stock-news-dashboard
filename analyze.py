"""
AI 자동 분석 스크립트 (2단계)
================================
Step 1 (Haiku)  : 시간대 내 가장 중요한 이슈 기사 5개 선별
Step 2 (Sonnet) : 선별된 기사 제목 + 본문으로 심층 분석
                  → sector / headline / ai_summary / stocks(종목+이유)
"""

import os
import json
import time
import anthropic
from supabase import create_client
from datetime import datetime, timezone, timedelta
from collections import defaultdict

# ─────────────────────────────────────────────
# 설정
# ─────────────────────────────────────────────

KST        = timezone(timedelta(hours=9))
HOURS_BACK = 24

MODEL_STEP1 = "claude-haiku-4-5"    # 빠른 선별용 (저렴)
MODEL_STEP2 = "claude-sonnet-4-5"   # 심층 분석용 (정확)

SUPABASE_URL  = os.environ["SUPABASE_URL"]
SUPABASE_KEY  = os.environ["SUPABASE_KEY"]
ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
claude   = anthropic.Anthropic(api_key=ANTHROPIC_KEY)


# ─────────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────────

def load_news() -> list:
    """최근 24시간 뉴스 로드 (본문 요약 포함)"""
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
    """이미 분석된 시간대 목록"""
    cutoff = (datetime.now(KST) - timedelta(hours=HOURS_BACK)).strftime("%Y-%m-%d %H:%M")
    result = (
        supabase.table("timeline_issues")
        .select("hour")
        .gte("hour", cutoff)
        .execute()
    )
    return {row["hour"] for row in result.data} if result.data else set()


# ─────────────────────────────────────────────
# Step 1 : 핵심 이슈 기사 선별 (Haiku)
# ─────────────────────────────────────────────

def step1_select_key_articles(hour: str, articles: list) -> list:
    """
    30개 기사 제목을 Haiku로 빠르게 훑어보고
    가장 중요한 이슈와 관련된 기사 인덱스 최대 5개를 선별합니다.
    """
    # 제목 목록만 전달 (빠른 처리)
    titles = "\n".join(
        f"{i}. [{a['source']}] {a['title']}"
        for i, a in enumerate(articles[:30])
    )

    prompt = f"""{hour} 증권 뉴스 중 시장에 가장 큰 영향을 줄 핵심 이슈와 관련된 기사 번호를 선택하세요.

규칙:
- 단일 이슈 중심으로 가장 임팩트 있는 기사 3~5개만 선택
- 같은 주제의 중복 기사는 1~2개만 포함
- 반드시 JSON 배열로만 응답 (예: [0, 3, 7, 12])

기사 목록:
{titles}"""

    try:
        msg  = claude.messages.create(
            model=MODEL_STEP1,
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()

        # JSON 배열 파싱
        if "[" in text:
            text = text[text.index("["):text.rindex("]") + 1]
        indices = json.loads(text)

        # 유효한 인덱스만 필터링
        selected = [articles[i] for i in indices if isinstance(i, int) and i < len(articles)]
        if selected:
            return selected

    except Exception as e:
        print(f"  ⚠️  Step1 오류: {e} → 상위 5개 기사로 대체")

    # 오류 시 상위 5개 반환
    return articles[:5]


# ─────────────────────────────────────────────
# Step 2 : 심층 분석 (Sonnet)
# ─────────────────────────────────────────────

def step2_deep_analysis(hour: str, key_articles: list) -> dict:
    """
    선별된 핵심 기사들의 제목 + 본문 요약을 Sonnet으로 심층 분석합니다.
    종목별 관련 이유까지 함께 생성합니다.
    """
    # 제목 + 본문 요약 조합
    articles_text = ""
    for i, a in enumerate(key_articles, 1):
        title   = a.get("title",   "")
        summary = a.get("summary", "").strip()
        source  = a.get("source",  "")
        # 본문 요약이 있으면 포함, 없으면 제목만
        if summary:
            articles_text += f"\n[기사 {i}] [{source}] {title}\n본문: {summary[:300]}\n"
        else:
            articles_text += f"\n[기사 {i}] [{source}] {title}\n"

    prompt = f"""다음은 {hour}의 핵심 증권 뉴스입니다. 기사 본문 내용까지 참고하여 분석해주세요.

반드시 아래 JSON 형식으로만 응답하세요 (설명 없이 JSON만):
{{
  "sector": "섹터명 1개 (반도체 / AI·로봇 / 2차전지 / 바이오 / 금융 / 에너지 / 자동차 / 유통 / 건설 등)",
  "headline": "핵심 이슈를 압축한 한 문장 제목 (40자 이내, 명사형)",
  "ai_summary": "투자자 관점의 심층 요약 3~4문장. 이슈의 배경·원인·시장 영향·전망을 구체적 수치와 함께 서술.",
  "stocks": [
    {{"name": "종목명", "reason": "이 종목이 관련된 구체적 이유 (15자 이내)"}},
    {{"name": "종목명", "reason": "이유"}},
    {{"name": "종목명", "reason": "이유"}}
  ]
}}

작성 기준:
- sector: 이슈를 대표하는 섹터 1개
- headline: 핵심 이슈를 한 줄로 압축, 구체적 수치 포함 권장
- ai_summary: 본문 내용 기반으로 배경·영향·향후 전망까지 서술 (단순 제목 나열 금지)
- stocks: 뉴스에서 직접 언급되거나 명백히 영향받는 국내 상장 종목, 최대 5개
          reason은 해당 종목이 왜 이 이슈와 관련있는지 투자자가 이해할 수 있게 작성

핵심 기사:
{articles_text}"""

    try:
        msg  = claude.messages.create(
            model=MODEL_STEP2,
            max_tokens=800,
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

        # stocks 형식 검증 및 정리
        raw_stocks = res.get("stocks", [])
        stocks = []
        for s in raw_stocks:
            if isinstance(s, dict) and s.get("name"):
                stocks.append({
                    "name":   s["name"].strip(),
                    "reason": s.get("reason", "").strip(),
                })
            elif isinstance(s, str) and s.strip():
                stocks.append({"name": s.strip(), "reason": ""})

        return {
            "sector":     res.get("sector",     "증권"),
            "headline":   res.get("headline",   "주요 이슈"),
            "ai_summary": res.get("ai_summary", ""),
            "stocks":     stocks,
        }

    except Exception as e:
        print(f"  ⚠️  Step2 오류: {e}")
        return {
            "sector":     "증권",
            "headline":   "AI 분석 오류",
            "ai_summary": "분석 중 오류가 발생했습니다. 다시 시도해 주세요.",
            "stocks":     [],
        }


# ─────────────────────────────────────────────
# 저장
# ─────────────────────────────────────────────

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
            "stocks":        data["stocks"],   # [{"name":..., "reason":...}]
            "article_count": len(articles),
            "source_list":   src_str,
        },
        on_conflict="hour",
    ).execute()


# ─────────────────────────────────────────────
# 메인
# ─────────────────────────────────────────────

def main():
    print("=" * 55)
    print(f"AI 자동 분석 시작: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    print(f"Step1 모델: {MODEL_STEP1}  |  Step2 모델: {MODEL_STEP2}")
    print("=" * 55)

    # 뉴스 로드
    articles = load_news()
    if not articles:
        print("수집된 뉴스가 없습니다. 종료합니다.")
        return
    print(f"총 {len(articles)}건 뉴스 로드 완료")

    # 시간대별 그룹화
    hour_map = defaultdict(list)
    for art in articles:
        if art.get("pubdate_kst"):
            hour_key = art["pubdate_kst"][:13] + ":00"
            hour_map[hour_key].append(art)

    print(f"시간대 {len(hour_map)}개 발견")

    # 미분석 시간대 추출
    analyzed = load_analyzed_hours()
    pending  = sorted(
        [h for h in hour_map if h not in analyzed],
        reverse=True,
    )

    if not pending:
        print("모든 시간대가 이미 분석되었습니다. ✅")
        return

    print(f"미분석 시간대 {len(pending)}개 → AI 분석 시작\n")

    # 시간대별 2단계 분석
    for i, hour in enumerate(pending):
        hour_articles = hour_map[hour]
        print(f"[{i+1}/{len(pending)}] {hour}  ({len(hour_articles)}건)")

        # Step 1: 핵심 기사 선별
        print(f"  → Step1: 핵심 기사 선별 중...")
        key_articles = step1_select_key_articles(hour, hour_articles)
        print(f"  → {len(key_articles)}개 기사 선별 완료")

        # Step 2: 심층 분석
        print(f"  → Step2: 본문 기반 심층 분석 중...")
        result = step2_deep_analysis(hour, key_articles)

        # 저장
        save_analysis(hour, result, hour_articles)

        # 결과 출력
        print(f"  ✅ [{result['sector']}] {result['headline']}")
        for s in result["stocks"]:
            print(f"     📌 {s['name']} : {s['reason']}")
        print()

        # API rate limit 방지
        if i < len(pending) - 1:
            time.sleep(2)

    print("=" * 55)
    print(f"분석 완료! {len(pending)}개 시간대 처리됨")
    print("=" * 55)


if __name__ == "__main__":
    main()
