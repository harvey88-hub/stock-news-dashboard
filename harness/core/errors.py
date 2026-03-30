"""
core/errors.py
==============
Harness 공통 예외 클래스.
각 모듈은 이 예외를 상속하거나 직접 raise하여
Harness가 일관되게 에러를 처리할 수 있도록 합니다.
"""


class HarnessError(Exception):
    """Harness 기본 예외"""


class CollectorError(HarnessError):
    """수집기 실행 중 복구 불가능한 오류"""
    def __init__(self, collector_name: str, reason: str):
        self.collector_name = collector_name
        super().__init__(f"[{collector_name}] {reason}")


class CollectorPartialError(HarnessError):
    """일부 소스 수집 실패 (전체 실패는 아님) — 파이프라인 계속 진행"""
    def __init__(self, failed_sources: list[str]):
        self.failed_sources = failed_sources
        super().__init__(f"일부 소스 수집 실패: {', '.join(failed_sources)}")


class AnalyzerError(HarnessError):
    """분석기 실행 중 오류"""
    def __init__(self, analyzer_name: str, reason: str):
        self.analyzer_name = analyzer_name
        super().__init__(f"[{analyzer_name}] {reason}")


class StoreError(HarnessError):
    """저장소 접근 오류"""
    def __init__(self, store_name: str, reason: str):
        self.store_name = store_name
        super().__init__(f"[{store_name}] {reason}")


class ConfigError(HarnessError):
    """설정 오류 (필수 값 누락 등)"""


class PipelineError(HarnessError):
    """파이프라인 실행 오류"""
    def __init__(self, pipeline_name: str, step: str, reason: str):
        self.pipeline_name = pipeline_name
        self.step = step
        super().__init__(f"Pipeline '{pipeline_name}' failed at '{step}': {reason}")
