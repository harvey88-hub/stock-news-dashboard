"""
collectors/rss_collector.py
============================
RSS 뉴스 수집기 (통합 버전).
기존 ai-news-dashboard와 stock-news-dashboard에 중복되어 있던
RSS 수집 로직을 하나로 통합합니다.

피드 목록은 config/default.yaml에서 관리하므로
피드 추가/변경 시 코드 수정 없이 YAML만 편집하면 됩니다.
"""

from __future__ import annotations
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

from core.config import AppConfig
from core.interfaces import Article
from core.logging import get_logger
from core.errors import CollectorPartialError

KST = timezone(timedelta(hours=9))


class RssCollector:
    """
    설정 파일의 feeds 목록을 순회하며 RSS를 수집합니다.

    Collector 프로토콜 구현::

        articles = RssCollector(config).collect(hours_back=1)
    """

    name = "rss"

    def __init__(self, config: AppConfig):
        self._cfg = config.rss
        self._log = get_logger("rss")

    # ──────────────────────────────────────
    # 공개 메서드
    # ──────────────────────────────────────

    def collect(self, hours_back: int | None = None, **kwargs) -> list[Article]:
        """
        모든 RSS 피드에서 최근 N시간 이내 기사를 수집합니다.

        Args:
            hours_back: 수집 범위(시간). None이면 설정값 사용.

        Returns:
            Article 목록 (중복 링크 제거됨)
        """
        hrs = hours_back if hours_back is not None else self._cfg.hours_back
        now_kst = datetime.now(KST)
        cutoff  = now_kst - timedelta(hours=hrs)

        self._log.info(f"RSS 수집 시작 — 피드 {len(self._cfg.feeds)}개, 최근 {hrs}시간")

        all_articles: list[Article] = []
        failed_sources: list[str]   = []

        for feed in self._cfg.feeds:
            try:
                items = self._parse_feed(feed.name, feed.url, now_kst, cutoff)
                all_articles.extend(items)
                self._log.info(f"  {feed.name}: {len(items)}건 ✓")
            except Exception as e:
                failed_sources.append(feed.name)
                self._log.warning(f"  {feed.name}: 실패 — {type(e).__name__}: {e}")

        # 링크 기준 중복 제거
        dedup = self._dedup(all_articles)

        # 최대 건수 제한
        if self._cfg.max_articles > 0:
            dedup = dedup[:self._cfg.max_articles]

        self._log.info(
            f"RSS 수집 완료 — 총 {len(dedup)}건 "
            f"(실패: {len(failed_sources)}개 소스)"
        )

        if failed_sources:
            raise CollectorPartialError(failed_sources)  # 경고지만 파이프라인은 계속 진행

        return dedup

    # ──────────────────────────────────────
    # 내부 메서드
    # ──────────────────────────────────────

    def _parse_feed(
        self,
        source_name: str,
        url: str,
        now_kst: datetime,
        cutoff: datetime,
    ) -> list[Article]:
        """단일 RSS 피드를 파싱하여 Article 목록을 반환합니다. 네트워크 오류 시 최대 3회 재시도."""
        max_retries = 3
        last_exc: Exception | None = None

        for attempt in range(max_retries):
            try:
                resp = requests.get(
                    url,
                    headers={"User-Agent": self._cfg.user_agent},
                    timeout=self._cfg.timeout_seconds,
                )
                resp.raise_for_status()

                # XML 파싱 (EUC-KR 인코딩 대응)
                content = resp.content
                try:
                    root = ET.fromstring(content)
                except ET.ParseError:
                    content = resp.content.decode("euc-kr").encode("utf-8")
                    root = ET.fromstring(content)

                entries = root.findall(".//item")
                if not entries:
                    entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")

                items: list[Article] = []
                for entry in entries:
                    article = self._parse_entry(source_name, entry, now_kst, cutoff)
                    if article:
                        items.append(article)

                return items

            except Exception as e:
                last_exc = e
                if attempt < max_retries - 1:
                    wait = 2 ** attempt  # 1초, 2초
                    self._log.warning(
                        f"      [{source_name}] 재시도 {attempt + 1}/{max_retries - 1} "
                        f"({type(e).__name__}) — {wait}초 후 재시도"
                    )
                    time.sleep(wait)

        raise last_exc

    def _parse_entry(
        self,
        source_name: str,
        entry: ET.Element,
        now_kst: datetime,
        cutoff: datetime,
    ) -> Article | None:
        """XML 엔트리 하나를 Article로 변환합니다. 시간 범위 밖이면 None을 반환합니다."""

        def find_el(*tags):
            for tag in tags:
                el = entry.find(tag)
                if el is not None:
                    return el
            return None

        title_el = find_el("title", "{http://www.w3.org/2005/Atom}title")
        date_el  = find_el(
            "pubDate",
            "{http://purl.org/dc/elements/1.1/}date",
            "{http://www.w3.org/2005/Atom}published",
            "{http://www.w3.org/2005/Atom}updated",
            "published", "updated",
        )
        link_el = find_el("link", "{http://www.w3.org/2005/Atom}link")
        desc_el = find_el(
            "description",
            "{http://www.w3.org/2005/Atom}summary",
            "{http://www.w3.org/2005/Atom}content",
            "{http://purl.org/rss/1.0/modules/content/}encoded",
        )

        title   = (title_el.text or "").strip() if title_el is not None else ""
        pubdate = (date_el.text  or "").strip() if date_el  is not None else ""
        link    = ""
        if link_el is not None:
            link = (link_el.text or link_el.get("href", "")).strip()
        summary = (desc_el.text or "").strip()[:500] if desc_el is not None else ""

        # 시간 필터
        pub_dt = self._parse_datetime(pubdate)
        if pub_dt is None:
            return None
        if pub_dt.tzinfo is None:
            pub_dt = pub_dt.replace(tzinfo=KST)
        if pub_dt < cutoff:
            return None

        pub_kst_str = pub_dt.astimezone(KST).strftime("%Y-%m-%d %H:%M")
        now_kst_str = now_kst.strftime("%Y-%m-%d %H:%M")

        return Article(
            source=source_name,
            title=title,
            link=link,
            published_at=pub_kst_str,
            collected_at=now_kst_str,
            summary=summary,
            pubdate_raw=pubdate,
        )

    @staticmethod
    def _parse_datetime(pub_date_str: str) -> datetime | None:
        """다양한 날짜 형식을 datetime으로 파싱합니다."""
        if not pub_date_str:
            return None
        for fn in (
            parsedate_to_datetime,
            lambda s: datetime.fromisoformat(s.replace("Z", "+00:00")),
            lambda s: datetime.strptime(s, "%Y-%m-%d %H:%M:%S"),
        ):
            try:
                return fn(pub_date_str)
            except Exception:
                continue
        return None

    @staticmethod
    def _dedup(articles: list[Article]) -> list[Article]:
        """링크 기준으로 중복 기사를 제거합니다."""
        seen:   set[str]       = set()
        result: list[Article]  = []
        for a in articles:
            key = a.link or a.title
            if key and key not in seen:
                seen.add(key)
                result.append(a)
            elif not key:
                result.append(a)
        return result
