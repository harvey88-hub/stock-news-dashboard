"""
AI 자동 분석 스크립트 (3단계)
================================
Step 1 (Haiku)  : 시간대 전체 기사에서 가장 중요한 이슈 1개 선정 + 관련 기사 추출
Step 2 (Sonnet) : 선별된 기사 제목 + 본문으로 배경·원인·전망 심층 분석
Step 3 (Haiku)  : 추출된 종목이 KOSPI/KOSDAQ 실제 상장 종목인지 필터링
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

MODEL_HAIKU  = "claude-haiku-4-5"   # Step 1, 3 (빠르고 저렴)
MODEL_SONNET = "claude-sonnet-4-5"  # Step 2 (정확하고 깊이있음)

SUPABASE_URL  = os.environ["SUPABASE_URL"]
SUPABASE_KEY  = os.environ["SUPABASE_KEY"]
ANTHROPIC_KEY = os.environ["ANTHROPIC_API_KEY"]

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
claude   = anthropic.Anthropic(api_key=ANTHROPIC_KEY)


# ─────────────────────────────────────────────
# 데이터 로드
# ─────────────────────────────────────────────

def load_news() -> list:
    """최근 24시간 뉴스 로드 (본문 포함)"""
    cutoff = (datetime.now(KST) - timedelta(hours=HOURS_BACK)).strftime("%Y-%m-%d %H:%M")
    result = (
        supabase.table("news_articles")
        .select("id, source, title, pubdate_kst, collected_at, link, summary")
        .gte("collected_at", cutoff)
        .order("collected_at", desc=True)
        .limit(1000)
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
# Step 1 : 핵심 이슈 1개 선정 + 관련 기사 추출 (Haiku)
# ─────────────────────────────────────────────

def step1_find_key_issue(hour: str, articles: list) -> list:
    """
    시간대 전체 기사 제목을 Haiku로 훑어보고
    가장 중요한 이슈 1개를 선정한 뒤
    그 이슈와 관련된 기사 인덱스를 반환합니다.
    """
    titles = "\n".join(
        f"{i}. [{a['source']}] {a['title']}"
        for i, a in enumerate(articles)
    )

    prompt = f"""{hour} 국내 증권 뉴스 {len(articles)}건입니다.

이 중 시장에 가장 큰 영향을 줄 핵심 이슈 1개를 선정하고,
그 이슈와 직접 관련된 기사 번호만 골라주세요.

반드시 JSON 형식으로만 응답하세요:
{{
  "issue": "핵심 이슈 한 줄 설명",
  "indices": [관련 기사 번호 목록]
}}

선정 기준:
- 가장 많은 언론사가 다루는 이슈
- 주가에 직접적인 영향을 줄 수 있는 이슈
- 중복 기사는 포함하되 완전히 무관한 기사는 제외

기사 목록:
{titles}"""

    try:
        msg  = claude.messages.create(
            model=MODEL_HAIKU,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()

        # JSON 파싱
        if "```" in text:
            parts = text.split("```")
            text  = parts[1] if len(parts) > 1 else text
            if text.lower().startswith("json"):
                text = text[4:]

        res     = json.loads(text.strip())
        issue   = res.get("issue", "")
        indices = res.get("indices", [])

        selected = [articles[i] for i in indices if isinstance(i, int) and i < len(articles)]

        if selected:
            print(f"  → 핵심 이슈: {issue}")
            print(f"  → 관련 기사 {len(selected)}건 선별")
            return selected

    except Exception as e:
        print(f"  ⚠️  Step1 오류: {e} → 상위 5개로 대체")

    return articles[:5]


# ─────────────────────────────────────────────
# Step 2 : 심층 분석 (Sonnet)
# ─────────────────────────────────────────────

def step2_deep_analysis(hour: str, key_articles: list) -> dict:
    """
    선별된 핵심 기사들의 제목 + 본문을 Sonnet으로 심층 분석합니다.
    배경·원인·전망과 종목별 관련 이유까지 생성합니다.
    """
    articles_text = ""
    for i, a in enumerate(key_articles, 1):
        title   = a.get("title",   "")
        summary = (a.get("summary") or "").strip()
        source  = a.get("source",  "")
        articles_text += f"\n[기사 {i}] [{source}] {title}\n"
        if summary:
            articles_text += f"본문: {summary[:400]}\n"

    prompt = f"""다음은 {hour}의 핵심 증권 뉴스입니다. 기사 제목과 본문을 모두 참고하여 분석해주세요.

반드시 아래 JSON 형식으로만 응답하세요 (설명 없이 JSON만):
{{
  "sector": "섹터명 1개 (반도체 / AI·로봇 / 2차전지 / 바이오 / 금융 / 에너지 / 자동차 / 유통 / 건설 등)",
  "headline": "핵심 이슈를 압축한 제목 (40자 이내, 명사형, 구체적 수치 포함 권장)",
  "ai_summary": "투자자 관점 심층 요약 3~4문장. 반드시 아래 순서로 작성:\n1) 이슈 발생 배경 및 원인\n2) 시장 및 관련 종목 영향\n3) 향후 전망 또는 주목 포인트",
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
        msg  = claude.messages.create(
            model=MODEL_SONNET,
            max_tokens=900,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()

        if "```" in text:
            parts = text.split("```")
            text  = parts[1] if len(parts) > 1 else text
            if text.lower().startswith("json"):
                text = text[4:]

        res        = json.loads(text.strip())
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
            "ai_summary": "분석 중 오류가 발생했습니다.",
            "stocks":     [],
        }


# ─────────────────────────────────────────────
# Step 3 : 상장 종목 검증 (Haiku)
# ─────────────────────────────────────────────

def step3_verify_listed_stocks(stocks: list) -> list:
    """
    AI가 추출한 종목명을 KOSPI/KOSDAQ 상장 종목으로 폭넓게 매핑합니다.

    - 직접 상장 종목 → 그대로 유지
    - 비상장이지만 관련 상장사 있음 → 상장사로 대체 (이유에 관계 명시)
      예) 두나무 → 카카오 (두나무 최대주주)
    - 관련 상장사 없는 비상장/외국기업 → 제외
    """
    if not stocks:
        return []

    stocks_info = [
        {"name": s["name"], "reason": s.get("reason", "")}
        for s in stocks
    ]

    prompt = f"""다음 종목/기업 목록을 검토하여 투자자가 참고할 수 있는 국내 상장 종목으로 매핑해주세요.

검증 대상:
{json.dumps(stocks_info, ensure_ascii=False, indent=2)}

처리 규칙:
1. KOSPI/KOSDAQ 직접 상장 종목 → 정확한 상장 종목명으로 그대로 포함
2. 비상장 기업이지만 KOSPI/KOSDAQ 상장된 지배주주·모회사·주요 관련사가 있으면 → 그 상장사로 대체
   예) 두나무(비상장, Upbit 운영) → 카카오(두나무 최대주주) 또는 한화투자증권
   예) 스페이스X → 관련 국내 상장사 없으면 제외
3. 관련 국내 상장사가 없는 비상장/외국 기업 → 제외
4. 종목명 오탈자 → 정확한 상장 종목명으로 수정

반드시 JSON 형식으로만 응답:
[
  {{"name": "상장종목명", "reason": "이슈와의 관련 이유 (대체된 경우 관계 포함) 25자 이내"}},
  ...
]

예시 응답:
[
  {{"name": "카카오", "reason": "두나무(Upbit) 최대주주"}},
  {{"name": "SK하이닉스", "reason": "HBM 주요 공급사"}}
]"""

    try:
        msg  = claude.messages.create(
            model=MODEL_HAIKU,
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()

        # JSON 파싱
        if "```" in text:
            parts = text.split("```")
            text  = parts[1] if len(parts) > 1 else text
            if text.lower().startswith("json"):
                text = text[4:]
        if "[" in text:
            text = text[text.index("["):text.rindex("]") + 1]

        raw      = json.loads(text)
        verified = []
        seen     = set()

        for item in raw:
            if not isinstance(item, dict):
                continue
            name   = item.get("name",   "").strip()
            reason = item.get("reason", "").strip()
            if name and name not in seen:
                seen.add(name)
                verified.append({"name": name, "reason": reason})

        before = [s["name"] for s in stocks]
        after  = [s["name"] for s in verified]
        print(f"  → 종목 검증: {before} → {after}")
        return verified

    except Exception as e:
        print(f"  ⚠️  Step3 오류: {e} → 원본 종목 그대로 사용")
        return stocks


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
    print("=" * 55)
    print(f"AI 자동 분석 시작: {datetime.now(KST).strftime('%Y-%m-%d %H:%M KST')}")
    print(f"Step1,3: {MODEL_HAIKU}  |  Step2: {MODEL_SONNET}")
    print("=" * 55)

    # 뉴스 로드
    articles = load_news()
    if not articles:
        print("수집된 뉴스가 없습니다. 종료합니다.")
        return
    print(f"총 {len(articles)}건 뉴스 로드 완료")

    # 시간대별 그룹화 (collected_at 기준 - KST 문자열 그대로 사용)
    hour_map = defaultdict(list)
    for art in articles:
        raw = art.get("collected_at") or art.get("pubdate_kst")
        if not raw:
            continue
        hour_key = raw[:13] + ":00"   # "2026-03-25 19:05" → "2026-03-25 19:00"
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

    print(f"미분석 시간대 {len(pending)}개 → 분석 시작\n")

    for i, hour in enumerate(pending):
        hour_articles = hour_map[hour]
        print(f"[{i+1}/{len(pending)}] {hour}  ({len(hour_articles)}건)")

        # Step 1: 핵심 이슈 선정 + 관련 기사 추출
        print(f"  [Step1] 핵심 이슈 선정 중...")
        key_articles = step1_find_key_issue(hour, hour_articles)

        # Step 2: 심층 분석
        print(f"  [Step2] 본문 기반 심층 분석 중...")
        result = step2_deep_analysis(hour, key_articles)

        # Step 3: 상장 종목 검증
        if result["stocks"]:
            print(f"  [Step3] 상장 종목 검증 중...")
            result["stocks"] = step3_verify_listed_stocks(result["stocks"])

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
