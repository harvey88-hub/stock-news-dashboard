import sys
sys.path.insert(0, '.')
errors = []

try:
    from core.interfaces import AnalysisResult, DailySummary, AnalysisTrace, Store
    ar = AnalysisResult(hour='t', sector='s', headline='h', ai_summary='a')
    assert hasattr(ar, 'impact_score'), "impact_score missing"
    assert hasattr(ar, 'is_evolution'), "is_evolution missing"
    assert hasattr(ar, 'evolution_type'), "evolution_type missing"
    at = AnalysisTrace(hour='t', created_at='now')
    assert hasattr(at, 'step0_removed_count'), "step0_removed_count missing"
    assert hasattr(at, 'summary_quality_passed'), "summary_quality_passed missing"
    assert hasattr(at, 'impact_score'), "impact_score in trace missing"
    assert hasattr(at, 'is_evolution'), "is_evolution in trace missing"
    ds = DailySummary(date='2026-04-02', created_at='now')
    print("[OK] core.interfaces")
except Exception as e:
    errors.append(f"[FAIL] core.interfaces: {e}")

try:
    from analyzers.claude_analyzer import ClaudeAnalyzer
    assert hasattr(ClaudeAnalyzer, '_step0_filter_articles')
    assert hasattr(ClaudeAnalyzer, '_step2c_summary_quality_agent')
    assert hasattr(ClaudeAnalyzer, '_scoring_agent')
    print("[OK] claude_analyzer")
except Exception as e:
    errors.append(f"[FAIL] claude_analyzer: {e}")

try:
    from analyzers.stock_matcher import StockMatcher
    assert hasattr(StockMatcher, '_relevance_check_agent')
    print("[OK] stock_matcher")
except Exception as e:
    errors.append(f"[FAIL] stock_matcher: {e}")

try:
    from pipelines.daily_summary import DailySummaryPipeline
    print("[OK] pipelines.daily_summary")
except Exception as e:
    errors.append(f"[FAIL] pipelines.daily_summary: {e}")

try:
    from stores.sqlite_store import SQLiteStore
    assert hasattr(SQLiteStore, 'save_daily_summary')
    assert hasattr(SQLiteStore, 'get_daily_summary')
    print("[OK] sqlite_store")
except Exception as e:
    errors.append(f"[FAIL] sqlite_store: {e}")

try:
    from stores.supabase_store import SupabaseStore
    assert hasattr(SupabaseStore, 'save_daily_summary')
    assert hasattr(SupabaseStore, 'get_daily_summary')
    print("[OK] supabase_store")
except Exception as e:
    errors.append(f"[FAIL] supabase_store: {e}")

if errors:
    print("\n=== 오류 ===")
    for e in errors:
        print(e)
    sys.exit(1)
else:
    print("\n=== 모든 검증 통과 ===")
