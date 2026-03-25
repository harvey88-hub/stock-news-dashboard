"""
증권 RSS 뉴스 수집 → Supabase DB 저장 스크립트
================================================
GitHub Actions에서 1시간마다 자동 실행됩니다.

환경 변수 필요:
  SUPABASE_URL   : Supabase 프로젝트 URL
  SUPABASE_KEY   : Supabase anon key
"""

import os
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from supabase import create_client

# ──────────────────────────────────────────────
# 설정
# ──────────────────────────────────────────────

HOURS_BACK   = 1       # 최근 몇 시간 이내 기사만 수집
MAX_ARTICLES = 1000    # 최대 수집 건수
DEBUG        = False

RSS_FEEDS = {
    "매일경제":    "https://www.mk.co.kr/rss/50200011/",
    "조선비즈":    "https://biz.chosun.com/arc/outboundfeeds/rss/category/stock/?outputType=xml",
    "파이낸셜뉴스": "https://www.fnnews.com/rss/r20/fn_realnews_stock.xml",
    "헤럴드경제":  "https://biz.heraldcorp.com/rss/google/finance",
    "한국경제":    "https://www.hankyung.com/feed/finance",
    "이데일리":   "http://rss.edaily.co.kr/stock_news.xml",
    "이투데이":   "https://rss.etoday.co.kr/eto/finance_news.xml",
    "연합뉴스":   "https://www.yonhapnewstv.co.kr/category/news/economy/feed/",
    "서울경제":   "https://www.sedaily.com/rss/finance",
}

HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}

KST = timezone(timedelta(hours=9))


# ──────────────────────────────────────────────
# 유틸 함수
# ──────────────────────────────────────────────

def parse_pubdate(pub_date_str):
    if not pub_date_str:
        return None
    try:
        return parsedate_to_datetime(pub_date_str)
    except Exception:
        pass
    try:
        normalized = pub_date_str.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    except Exception:
        pass
    try:
        return datetime.strptime(pub_date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
    except Exception:
        pass
    return None


def is_recent(pub_date_str, now_kst):
    dt = parse_pubdate(pub_date_str)
    if dt is None:
        return False
    cutoff = now_kst - timedelta(hours=HOURS_BACK)
    return dt >= cutoff


def format_pubdate_kst(pub_date_str):
    dt = parse_pubdate(pub_date_str)
    if dt is None:
        return pub_date_str
    return dt.astimezone(KST).strftime("%Y-%m-%d %H:%M")


def find_el(item, *tags):
    for tag in tags:
        el = item.find(tag)
        if el is not None:
            return el
    return None


def parse_rss(source_name, url, now_kst):
    items = []
    try:
        resp = requests.get(url, headers=HTTP_HEADERS, timeout=10)
        resp.raise_for_status()

        content = resp.content
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            content = resp.content.decode("euc-kr").encode("utf-8")
            root = ET.fromstring(content)

        entries = root.findall(".//item")
        if not entries:
            entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")

        for idx, item in enumerate(entries):
            if DEBUG and idx == 0:
                print(f"\n  [DEBUG] {source_name} 첫 기사 XML 태그:")
                for child in item:
                    val = (child.text or "").strip().replace("\n", " ")[:80]
                    print(f"    <{child.tag}> = '{val}'")

            title_el = find_el(item, "title", "{http://www.w3.org/2005/Atom}title")
            date_el  = find_el(item,
                "pubDate",
                "{http://purl.org/dc/elements/1.1/}date",
                "{http://www.w3.org/2005/Atom}published",
                "{http://www.w3.org/2005/Atom}updated",
                "published", "updated",
            )
            link_el  = find_el(item, "link", "{http://www.w3.org/2005/Atom}link")
            link_val = ""
            if link_el is not None:
                link_val = (link_el.text or link_el.get("href", "")).strip()

            desc_el = find_el(item,
                "description",
                "{http://www.w3.org/2005/Atom}summary",
                "{http://www.w3.org/2005/Atom}content",
                "{http://purl.org/rss/1.0/modules/content/}encoded",
            )

            title   = (title_el.text or "").strip() if title_el is not None else ""
            pubdate = (date_el.text  or "").strip() if date_el  is not None else ""
            link    = link_val
            desc    = (desc_el.text  or "").strip()[:500] if desc_el is not None else ""

            if not is_recent(pubdate, now_kst):
                continue

            items.append({
                "collected_at": now_kst.strftime("%Y-%m-%d %H:%M"),
                "source":       source_name,
                "title":        title,
                "pubdate_raw":  pubdate,
                "pubdate_kst":  format_pubdate_kst(pubdate),
                "link":         link,
                "summary":      desc,
            })

    except requests.exceptions.HTTPError as e:
        print(f"  [HTTP 오류] {source_name}: {e}")
    except ET.ParseError as e:
        print(f"  [XML 오류] {source_name}: {e}")
    except Exception as e:
        print(f"  [오류] {source_name}: {type(e).__name__}: {e}")

    return items


# ──────────────────────────────────────────────
# Supabase 저장
# ──────────────────────────────────────────────

def save_to_supabase(articles):
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    client = create_client(url, key)

    if not articles:
        return 0

    # link 기준 중복 방지 (upsert)
    result = (
        client.table("news_articles")
        .upsert(articles, on_conflict="link")
        .execute()
    )
    return len(result.data) if result.data else 0


# ──────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────

def main():
    now_kst = datetime.now(KST)

    print("=" * 55)
    print("  증권 RSS 뉴스 수집 → Supabase 저장")
    print(f"  실행 시각: {now_kst.strftime('%Y-%m-%d %H:%M KST')}")
    print(f"  수집 범위: 최근 {HOURS_BACK}시간 이내")
    print("=" * 55)

    print(f"\n RSS 수집 중...\n")
    all_articles = []
    for source_name, url in RSS_FEEDS.items():
        articles = parse_rss(source_name, url, now_kst)
        all_articles.extend(articles)
        status = f"✅ {len(articles)}건" if articles else "⚠️  0건"
        print(f"  {source_name}: {status}")

    if MAX_ARTICLES > 0:
        all_articles = all_articles[:MAX_ARTICLES]

    print(f"\n  총 수집: {len(all_articles)}건")

    if not all_articles:
        print(f"\n⚠️  최근 {HOURS_BACK}시간 이내 수집된 기사가 없습니다.")
        return

    print("\n💾 Supabase 저장 중...")
    saved = save_to_supabase(all_articles)
    print(f"\n✅ 완료! {saved}건 저장 (중복 제외)")


if __name__ == "__main__":
    main()
