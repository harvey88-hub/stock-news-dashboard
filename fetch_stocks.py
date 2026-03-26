"""
KRX 상장 종목 수집 스크립트
================================
금융위원회 KRX상장종목정보 API를 호출하여
KOSPI + KOSDAQ 전체 종목을 Supabase listed_stocks 테이블에 저장합니다.
매일 1회 GitHub Actions에서 자동 실행됩니다.
"""

import os
import sys
import requests
from datetime import datetime, timedelta
from supabase import create_client

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
KRX_API_KEY  = os.environ["KRX_API_KEY"]

BASE_URL = "https://apis.data.go.kr/1160100/service/GetKrxListedInfoService/getItemInfo"


def fetch_market(market: str, base_date: str) -> list:
    """KOSPI 또는 KOSDAQ 전체 종목 수집"""
    all_items = []
    page = 1

    while True:
        params = {
            "serviceKey": KRX_API_KEY,
            "numOfRows":  3000,
            "pageNo":     page,
            "resultType": "json",
            "basDt":      base_date,
            "mrktCtg":    market,
        }

        try:
            resp = requests.get(BASE_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  ⚠️  {market} 페이지 {page} 오류: {e}")
            break

        body      = data.get("response", {}).get("body", {})
        items_obj = body.get("items", {})

        if not items_obj:
            break

        item_list = items_obj.get("item", [])
        if not item_list:
            break

        # 단일 결과인 경우 dict로 반환되므로 list로 변환
        if isinstance(item_list, dict):
            item_list = [item_list]

        all_items.extend(item_list)

        total = int(body.get("totalCount", 0))
        if len(all_items) >= total:
            break

        page += 1

    return all_items


def main():
    supabase   = create_client(SUPABASE_URL, SUPABASE_KEY)
    today      = datetime.now().strftime("%Y%m%d")
    yesterday  = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

    print("=" * 55)
    print(f"KRX 상장 종목 수집 시작: {today}")
    print("=" * 55)

    all_stocks = []

    for market in ["KOSPI", "KOSDAQ"]:
        print(f"\n{market} 수집 중...")

        # 오늘 기준 시도, 실패 시 어제 기준으로 재시도 (장 마감 전 데이터 없을 수 있음)
        items = fetch_market(market, today)
        if not items:
            print(f"  오늘 데이터 없음 → 어제({yesterday}) 기준으로 재시도")
            items = fetch_market(market, yesterday)

        print(f"  {market}: {len(items)}건 수집")

        for item in items:
            code = item.get("srtnCd", "").strip()
            name = item.get("itmsNm", "").strip()

            if not code or not name:
                continue

            all_stocks.append({
                "stock_code": code,
                "stock_name": name,
                "market":     item.get("mrktCtg", market).strip(),
                "isin_code":  item.get("isinCd",  "").strip(),
                "corp_name":  item.get("corpNm",  "").strip(),
                "updated_at": datetime.now().isoformat(),
            })

    if not all_stocks:
        print("\n❌ 수집된 종목 없음 - 종료")
        sys.exit(1)

    # 중복 제거 (stock_code 기준)
    seen  = set()
    dedup = []
    for s in all_stocks:
        if s["stock_code"] not in seen:
            seen.add(s["stock_code"])
            dedup.append(s)

    print(f"\n💾 Supabase 저장 중... (총 {len(dedup)}개 종목)")

    # 배치 단위로 upsert (Supabase 한번에 최대 1000건)
    batch_size = 500
    for i in range(0, len(dedup), batch_size):
        batch = dedup[i:i + batch_size]
        supabase.table("listed_stocks").upsert(
            batch, on_conflict="stock_code"
        ).execute()
        print(f"  저장 완료: {i + len(batch)}/{len(dedup)}")

    print(f"\n✅ 완료! KOSPI+KOSDAQ 총 {len(dedup)}개 종목 저장")
    print("=" * 55)


if __name__ == "__main__":
    main()
