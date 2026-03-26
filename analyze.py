"""
AI 자동 분석 스크립트 (3단계)
================================
Step 1 (Haiku)  : 시간대 전체 기사에서 가장 중요한 이슈 1개 선정 + 관련 기사 추출
Step 2 (Sonnet) : 선별된 기사 제목 + 본문으로 배경·원인·전망 심층 분석
Step 3 (DB+AI)  : listed_stocks DB로 직접 매칭 → 미매칭 시 Haiku로 관련 상장사 탐색
"""

import os
import json
import time
import difflib
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


def load_listed_stocks() -> dict:
    """
    listed_stocks 테이블에서 전체 상장 종목 로드
    반환: {종목명: 종목코드} 딕셔너리
    """
    result = (
        supabase.table("listed_stocks")
        .select("stock_code, stock_name")
        .execute()
    )
    if not result.data:
        return {}
    return {row["stock_name"]: row["stock_code"] for row in result.data}


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
# Step 3 : DB 기반 상장 종목 검증 + AI 보조
# ─────────────────────────────────────────────

def step3_verify_stocks(stocks: list, listed: dict) -> list:
    """
    DB 상장 종목 리스트 기반으로 3단계 매칭 후 미매칭은 Haiku로 처리합니다.

    1단계 (정확한 매칭)  : 종목명이 DB에 정확히 존재
    2단계 (유사 매칭)    : difflib으로 85% 이상 유사한 이름 매칭
    3단계 (부분 매칭)    : 종목명이 DB 이름에 포함되거나 DB 이름이 종목명에 포함
    AI 보조              : 위 3단계 모두 실패 시 Haiku로 관련 상장사 탐색
                          예) 두나무 → 카카오(최대주주)
    """
    if not stocks:
        return []

    verified    = []
    unmatched   = []
    seen        = set()
    stock_names = list(listed.keys())  # DB 종목명 전체 리스트

    for stock in stocks:
        name   = stock.get("name",   "").strip()
        reason = stock.get("reason", "").strip()

        if not name or name in seen:
            continue

        # ── 1단계: 정확한 이름 매칭 ──────────────────
        if name in listed:
            verified.append({"name": name, "reason": reason})
            seen.add(name)
            continue

        # ── 2단계: difflib 유사 매칭 (85% 이상) ──────
        close = difflib.get_close_matches(name, stock_names, n=1, cutoff=0.85)
        if close:
            matched = close[0]
            if matched not in seen:
                verified.append({"name": matched, "reason": reason})
                seen.add(matched)
            continue

        # ── 3단계: 부분 문자열 매칭 ──────────────────
        # 공백·괄호 제거 후 비교
        name_clean = name.replace(" ", "").replace("(주)", "").replace("㈜", "")
        partial = [
            n for n in stock_names
            if name_clean in n.replace(" ", "") or n.replace(" ", "") in name_clean
        ]
        if partial:
            best = min(partial, key=len)   # 가장 정확한(짧은) 이름 선택
            if best not in seen:
                verified.append({"name": best, "reason": reason})
                seen.add(best)
            continue

        # ── AI 보조 대상으로 분류 ─────────────────────
        unmatched.append(stock)

    # ── AI 보조: 비상장/외국기업 → 관련 상장사 매핑 ──
    if unmatched:
        print(f"  → DB 미매칭 {len(unmatched)}건 → AI 보조 탐색")
        ai_results = step3_ai_fallback(unmatched)
        for item in ai_results:
            name = item.get("name", "").strip()
            if name and name in listed and name not in seen:
                verified.append(item)
                seen.add(name)

    before = [s["name"] for s in stocks]
    after  = [s["name"] for s in verified]
    print(f"  → 종목 검증: {before} → {after}")
    return verified


def step3_ai_fallback(stocks: list) -> list:
    """
    DB 매칭 실패한 종목을 Haiku로 처리합니다.
    비상장 기업의 경우 관련 상장사를 찾아 대체합니다.
    """
    stocks_info = [
        {"name": s["name"], "reason": s.get("reason", "")}
        for s in stocks
    ]

    prompt = f"""다음 종목/기업이 KOSPI/KOSDAQ 상장 종목 DB에서 찾을 수 없었습니다.
비상장 기업이라면 관련 상장사(지배주주·모회사·주요 관련사)로 대체해주세요.

검증 대상:
{json.dumps(stocks_info, ensure_ascii=False, indent=2)}

처리 규칙:
1. 비상장이지만 관련 상장사 있음 → 상장사명으로 대체 (이유에 관계 명시)
   예) 두나무 → 카카오 / 이유: "두나무(Upbit) 최대주주"
2. 외국 기업 → 관련 국내 상장사가 명확하면 포함, 없으면 제외
3. 관련 국내 상장사가 없으면 → 빈 배열에 포함하지 않음

반드시 JSON 배열로만 응답 (없으면 빈 배열 []):
[
  {{"name": "상장종목명", "reason": "관계 포함 이유 25자 이내"}},
  ...
]"""

    try:
        msg  = claude.messages.create(
            model=MODEL_HAIKU,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        text = msg.content[0].text.strip()

        if "```" in text:
            parts = text.split("```")
            text  = parts[1] if len(parts) > 1 else text
            if text.lower().startswith("json"):
                text = text[4:]
        if "[" in text:
            text = text[text.index("["):text.rindex("]") + 1]

        raw  = json.loads(text)
        seen = set()
        out  = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            name = item.get("name", "").strip()
            if name and name not in seen:
                seen.add(name)
                out.append({"name": name, "reason": item.get("reason", "").strip()})
        return out

    except Exception as e:
        print(f"  ⚠️  Step3 AI 보조 오류: {e}")
        return []


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

    # 상장 종목 DB 로드 (Step 3에서 재사용)
    print("📋 상장 종목 DB 로드 중...")
    listed_stocks = load_listed_stocks()
    if listed_stocks:
        print(f"   → {len(listed_stocks)}개 종목 로드 완료 (KOSPI+KOSDAQ)")
    else:
        print("   ⚠️  상장 종목 DB 없음 → AI 단독 검증으로 대체")

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

        # Step 3: DB 기반 상장 종목 검증
        if result["stocks"]:
            print(f"  [Step3] DB 기반 상장 종목 검증 중...")
            result["stocks"] = step3_verify_stocks(result["stocks"], listed_stocks)

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
