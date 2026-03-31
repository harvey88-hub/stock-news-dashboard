"""
core/logging.py
===============
구조화된 로깅 유틸리티.
파이프라인 단계별 진행 상황을 일관된 형식으로 출력합니다.
"""

from __future__ import annotations
import sys
import logging
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))


def _now_kst() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")


class HarnessFormatter(logging.Formatter):
    """컬러 없이 구조화된 로그 포맷"""

    LEVEL_MAP = {
        logging.DEBUG:    "DEBUG",
        logging.INFO:     "INFO ",
        logging.WARNING:  "WARN ",
        logging.ERROR:    "ERROR",
        logging.CRITICAL: "CRIT ",
    }

    def format(self, record: logging.LogRecord) -> str:
        level = self.LEVEL_MAP.get(record.levelno, "INFO ")
        name  = record.name.ljust(14)[:14]
        ts    = _now_kst()
        msg   = record.getMessage()
        return f"[{ts}] {level} {name} | {msg}"


def get_logger(name: str) -> logging.Logger:
    """Harness 공통 로거를 반환합니다."""
    logger = logging.getLogger(f"harness.{name}")
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(HarnessFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
    return logger


# ──────────────────────────────────────────
# 파이프라인 진행 로그 헬퍼
# ──────────────────────────────────────────

class PipelineLogger:
    """파이프라인 실행 컨텍스트 로거"""

    def __init__(self, pipeline_name: str):
        self._log = get_logger("pipeline")
        self.name = pipeline_name
        self._step = 0
        self._total_steps = 0

    def start(self, total_steps: int = 0):
        self._total_steps = total_steps
        self._log.info(f"Pipeline '{self.name}' started")

    def step(self, description: str):
        self._step += 1
        prefix = f"[{self._step}/{self._total_steps}] " if self._total_steps else ""
        self._log.info(f"{prefix}{description}")

    def success(self, message: str):
        self._log.info(f"✓ {message}")

    def warn(self, message: str):
        self._log.warning(message)

    def error(self, message: str, exc: Exception | None = None):
        if exc:
            self._log.error(f"{message} — {type(exc).__name__}: {exc}")
        else:
            self._log.error(message)

    def finish(self, summary: str):
        self._log.info(f"Pipeline '{self.name}' complete — {summary}")
        self._log.info("=" * 55)
