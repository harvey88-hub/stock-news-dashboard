-- Supabase SQL Editor에서 실행하세요

CREATE TABLE IF NOT EXISTS news_articles (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    collected_at TEXT,
    source       TEXT,
    title        TEXT,
    pubdate_raw  TEXT,
    pubdate_kst  TEXT,
    link         TEXT UNIQUE,   -- 중복 방지 기준
    summary      TEXT,
    ai_summary   TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- 성능을 위한 인덱스
CREATE INDEX IF NOT EXISTS idx_news_pubdate ON news_articles (pubdate_kst DESC);
CREATE INDEX IF NOT EXISTS idx_news_source  ON news_articles (source);

-- 오래된 기사 자동 삭제 (30일 이상) — 선택 사항
-- DELETE FROM news_articles WHERE created_at < NOW() - INTERVAL '30 days';
