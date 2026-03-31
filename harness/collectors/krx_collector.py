"""
collectors/krx_collector.py
============================
KRX 상장 종목 수집기.
금융위원회 공공 API에서 KOSPI + KOSDAQ 전체 종목을 가져옵니다.
"""

from __future__ import annotations
import sys
import requests
from datetime import datetime, timedelta

from core.config import AppConfig
from core.interfaces import Article, ListedStock
from core.logging import get_logger
from core.errors import CollectorError


class KrxCollector:
    """
    KRX 상장 종목 수집기.

    Collector 프로토콜과의 호환성을 위해 collect()를 구현하지만
    반환값은 Article 대신 ListedStock을 담은 래퍼로 전달합니다.
    파이프라인은 타입을 확인하여 적절히 처리합니다.

    직접 사용::

        stocks = KrxCollector(config).collect_stocks()
    """

    name = "krx"

    def __init__(self, config: AppConfig):
        self._cfg = config.krx
        self._api_key = config.krx_api_key
        self._log = get_logger("krx")

    def collect(self, **kwargs) -> list[Article]:
        """Collector 프로토콜 호환용 래퍼 (stocks를 Article로 반환하지 않음)."""
        # 파이프라인에서 ListedStock 목록을 얻을 때는 collect_stocks()를 직접 사용합니다.
        # 이 메서드는 파이프라인 인터페이스 호환성을 위해서만 존재합니다.
        return []  # pragma: no cover

    def collect_stocks(self) -> list[ListedStock]:
        """
        KOSPI + KOSDAQ 전체 종목을 수집합니다.

        Returns:
            ListedStock 목록

        Raises:
            CollectorError: 수집된 종목이 0개인 경우
        """
        if not self._api_key:
            raise CollectorError("krx", "KRX_API_KEY 환경 변수가 설정되지 않았습니다.")

        today     = datetime.now().strftime("%Y%m%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")

        self._log.info(f"KRX 종목 수집 시작 — 기준일: {today}")

        all_stocks: list[ListedStock] = []

        for market in self._cfg.markets:
            self._log.info(f"  {market} 수집 중...")
            items = self._fetch_market(market, today)
            if not items:
                self._log.warning(f"  {market}: 오늘 데이터 없음 → 어제 기준 재시도")
                items = self._fetch_market(market, yesterday)
            self._log.info(f"  {market}: {len(items)}건 ✓")
            all_stocks.extend(items)

        # 중복 제거 (stock_code 기준)
        seen:  set[str]            = set()
        dedup: list[ListedStock]   = []
        for s in all_stocks:
            if s.stock_code not in seen:
                seen.add(s.stock_code)
                dedup.append(s)

        if not dedup:
            raise CollectorError("krx", "수집된 종목이 없습니다. API 키 또는 날짜를 확인하세요.")

        self._log.info(f"KRX 수집 완료 — KOSPI+KOSDAQ 총 {len(dedup)}개 종목")
        return dedup

    # ──────────────────────────────────────
    # 내부 메서드
    # ──────────────────────────────────────

    def _fetch_market(self, market: str, base_date: str) -> list[ListedStock]:
        """단일 시장(KOSPI 또는 KOSDAQ)의 종목을 페이지네이션으로 수집합니다."""
        all_items: list[ListedStock] = []
        page = 1

        while True:
            params = {
                "serviceKey": self._api_key,
                "numOfRows":  self._cfg.batch_size,
                "pageNo":     page,
                "resultType": "json",
                "basDt":      base_date,
                "mrktCtg":    market,
            }

            try:
                resp = requests.get(self._cfg.base_url, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except Exception as e:
                self._log.warning(f"  {market} 페이지 {page} 오류: {e}")
                break

            body      = data.get("response", {}).get("body", {})
            items_obj = body.get("items", {})
            if not items_obj:
                break

            item_list = items_obj.get("item", [])
            if not item_list:
                break
            if isinstance(item_list, dict):
                item_list = [item_list]

            for item in item_list:
                code = item.get("srtnCd", "").strip()
                name = item.get("itmsNm", "").strip()
                if code and name:
                    all_items.append(ListedStock(
                        stock_code=code,
                        stock_name=name,
                        market=item.get("mrktCtg", market).strip(),
                        isin_code=item.get("isinCd", "").strip(),
                        corp_name=item.get("corpNm", "").strip(),
                    ))

            total = int(body.get("totalCount", 0))
            if len(all_items) >= total:
                break
            page += 1

        return all_items
