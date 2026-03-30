#!/usr/bin/env python3
"""
cli.py — 트랜드AI Harness 단일 진입점
======================================

사용법:
    python cli.py pipeline hourly-news           # 매시간 뉴스 수집+분석
    python cli.py pipeline daily-stocks          # 일간 KRX 종목 업데이트
    python cli.py pipeline hourly-news --dry-run # 저장 없이 시뮬레이션

    python cli.py collect rss                    # RSS만 수집
    python cli.py collect krx                    # KRX 종목만 수집

    python cli.py serve                          # Streamlit UI 실행
    python cli.py status                         # 현재 DB 상태 요약

환경 변수:
    SUPABASE_URL        Supabase 프로젝트 URL (없으면 SQLite 로컬 모드)
    SUPABASE_KEY        Supabase anon key
    ANTHROPIC_API_KEY   Claude API 키 (분석에 필요)
    KRX_API_KEY         공공 데이터 포털 API 키 (KRX 수집에 필요)
"""

import sys
import argparse
from pathlib import Path

# 패키지 경로 추가
sys.path.insert(0, str(Path(__file__).parent))

from core.harness import Harness
from core.logging import get_logger

log = get_logger("cli")


# ──────────────────────────────────────────
# 서브커맨드 핸들러
# ──────────────────────────────────────────

def cmd_pipeline(args, harness: Harness):
    """파이프라인 실행"""
    name    = args.name.replace("-", "_")   # hourly-news → hourly_news
    dry_run = getattr(args, "dry_run", False)

    log.info(f"파이프라인 실행: {name}" + (" [dry-run]" if dry_run else ""))
    result = harness.run_pipeline(name, dry_run=dry_run)
    log.info(f"결과: {result}")


def cmd_collect(args, harness: Harness):
    """단일 수집기 실행"""
    source = args.source

    if source == "rss":
        from collectors.rss_collector import RssCollector
        collector = RssCollector(harness.config)
        articles  = collector.collect()
        store     = harness.get_store()
        saved     = store.save_articles(articles)
        log.info(f"RSS 수집 완료: {len(articles)}건 수집, {saved}건 저장")

    elif source == "krx":
        from collectors.krx_collector import KrxCollector
        collector = KrxCollector(harness.config)
        stocks    = collector.collect_stocks()
        store     = harness.get_store()
        saved     = store.save_stocks(stocks)
        log.info(f"KRX 수집 완료: {len(stocks)}개 종목, {saved}개 저장")

    else:
        log.error(f"알 수 없는 소스: {source}. 사용 가능: rss, krx")
        sys.exit(1)


def cmd_serve(args, harness: Harness):
    """Streamlit UI 실행"""
    import subprocess
    ui_path = Path(__file__).parent / "ui" / "streamlit_app.py"
    log.info(f"Streamlit UI 시작: {ui_path}")
    subprocess.run([sys.executable, "-m", "streamlit", "run", str(ui_path)], check=True)


def cmd_status(args, harness: Harness):
    """현재 DB 상태 요약"""
    store     = harness.get_store()
    articles  = store.get_articles(hours_back=24)
    analyses  = store.get_analyses(hours_back=24)
    stocks    = store.get_listed_stocks()

    log.info("=" * 40)
    log.info(f"DB 상태 요약 (최근 24시간)")
    log.info(f"  뉴스 기사:    {len(articles)}건")
    log.info(f"  분석 결과:    {len(analyses)}건")
    log.info(f"  상장 종목:    {len(stocks)}개")
    if analyses:
        latest = analyses[0]
        log.info(f"  최신 분석:    {latest.hour} [{latest.sector}] {latest.headline}")
    log.info("=" * 40)


# ──────────────────────────────────────────
# 메인
# ──────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cli.py",
        description="트랜드AI Harness CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # pipeline
    p_pipeline = sub.add_parser("pipeline", help="파이프라인 실행")
    p_pipeline.add_argument("name", choices=["hourly-news", "daily-stocks"], help="파이프라인 이름")
    p_pipeline.add_argument("--dry-run", action="store_true", help="저장 없이 시뮬레이션")

    # collect
    p_collect = sub.add_parser("collect", help="단일 수집기 실행")
    p_collect.add_argument("source", choices=["rss", "krx"], help="수집 소스")

    # serve
    sub.add_parser("serve", help="Streamlit UI 실행")

    # status
    sub.add_parser("status", help="현재 DB 상태 요약")

    return parser


def main():
    parser = build_parser()
    args   = parser.parse_args()

    # Harness 초기화 (환경 변수 자동 감지)
    harness = Harness.with_defaults()

    commands = {
        "pipeline": cmd_pipeline,
        "collect":  cmd_collect,
        "serve":    cmd_serve,
        "status":   cmd_status,
    }

    handler = commands.get(args.command)
    if handler:
        handler(args, harness)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
