"""
tests/unit/test_collectors.py
==============================
RssCollector, KrxCollector 단위 테스트.
실제 HTTP 요청 없이 목(mock)으로 테스트합니다.
"""

import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.config import AppConfig, RssCollectorConfig, RssFeed
from core.interfaces import Article
from collectors.rss_collector import RssCollector

KST = timezone(timedelta(hours=9))


# ──────────────────────────────────────────
# 픽스처
# ──────────────────────────────────────────

@pytest.fixture
def rss_config():
    """테스트용 설정 (실제 피드 URL 없이)"""
    cfg = AppConfig()
    cfg.rss = RssCollectorConfig(
        hours_back=1,
        max_articles=100,
        timeout_seconds=5,
        feeds=[
            RssFeed(name="테스트뉴스", url="http://test.example.com/rss", category="test"),
        ],
    )
    return cfg


@pytest.fixture
def sample_rss_xml():
    """테스트용 RSS XML"""
    now_rfc = datetime.now(KST).strftime("%a, %d %b %Y %H:%M:%S +0900")
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>테스트 뉴스</title>
    <item>
      <title>삼성전자, AI 반도체 신제품 발표</title>
      <link>http://test.example.com/news/1</link>
      <pubDate>{now_rfc}</pubDate>
      <description>삼성전자가 차세대 AI 반도체를 공개했습니다.</description>
    </item>
    <item>
      <title>SK하이닉스, HBM4 양산 시작</title>
      <link>http://test.example.com/news/2</link>
      <pubDate>{now_rfc}</pubDate>
      <description>SK하이닉스가 HBM4 양산에 돌입했습니다.</description>
    </item>
  </channel>
</rss>"""


# ──────────────────────────────────────────
# RssCollector 테스트
# ──────────────────────────────────────────

class TestRssCollector:

    def test_collect_returns_articles(self, rss_config, sample_rss_xml):
        """RSS 수집 시 Article 목록을 반환해야 한다"""
        mock_response = MagicMock()
        mock_response.content = sample_rss_xml.encode("utf-8")
        mock_response.raise_for_status = MagicMock()

        with patch("collectors.rss_collector.requests.get", return_value=mock_response):
            collector = RssCollector(rss_config)
            articles  = collector.collect(hours_back=1)

        assert len(articles) == 2
        assert all(isinstance(a, Article) for a in articles)
        assert articles[0].source == "테스트뉴스"
        assert "삼성전자" in articles[0].title

    def test_dedup_removes_duplicate_links(self, rss_config, sample_rss_xml):
        """같은 링크의 기사는 중복 제거되어야 한다"""
        # 같은 기사를 두 번 포함하는 RSS
        dup_xml = sample_rss_xml.replace(
            "</channel>",
            """<item>
              <title>삼성전자 중복 기사</title>
              <link>http://test.example.com/news/1</link>
              <pubDate></pubDate>
            </item></channel>"""
        )
        mock_response = MagicMock()
        mock_response.content = dup_xml.encode("utf-8")
        mock_response.raise_for_status = MagicMock()

        with patch("collectors.rss_collector.requests.get", return_value=mock_response):
            collector = RssCollector(rss_config)
            articles  = collector.collect(hours_back=1)

        links = [a.link for a in articles]
        assert len(links) == len(set(links)), "중복 링크가 제거되지 않음"

    def test_outdated_articles_are_filtered(self, rss_config):
        """수집 범위를 벗어난 기사는 필터링되어야 한다"""
        old_date = "Mon, 01 Jan 2024 00:00:00 +0900"
        old_xml  = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>오래된 기사</title>
      <link>http://test.example.com/old/1</link>
      <pubDate>{old_date}</pubDate>
    </item>
  </channel>
</rss>"""
        mock_response = MagicMock()
        mock_response.content = old_xml.encode("utf-8")
        mock_response.raise_for_status = MagicMock()

        with patch("collectors.rss_collector.requests.get", return_value=mock_response):
            collector = RssCollector(rss_config)
            articles  = collector.collect(hours_back=1)

        assert len(articles) == 0, "오래된 기사가 필터링되지 않음"

    def test_article_has_required_fields(self, rss_config, sample_rss_xml):
        """Article 필드가 올바르게 채워져야 한다"""
        mock_response = MagicMock()
        mock_response.content = sample_rss_xml.encode("utf-8")
        mock_response.raise_for_status = MagicMock()

        with patch("collectors.rss_collector.requests.get", return_value=mock_response):
            collector = RssCollector(rss_config)
            articles  = collector.collect(hours_back=1)

        a = articles[0]
        assert a.source == "테스트뉴스"
        assert a.link.startswith("http")
        assert a.collected_at != ""
        assert a.published_at != ""
