-- ─────────────────────────────────────────────────────────────
--  schema.sql  |  Supabase PostgreSQL Schema
--  Run in: Supabase Dashboard → SQL Editor → New Query
-- ─────────────────────────────────────────────────────────────

-- ── Users ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email      TEXT UNIQUE NOT NULL,
  plan       TEXT NOT NULL DEFAULT 'free'
             CHECK (plan IN ('free', 'pro', 'enterprise')),
  li_handle  TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

-- ── Posts ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS posts (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     TEXT NOT NULL DEFAULT 'default',
  topic       TEXT NOT NULL,
  niche       TEXT,
  content     TEXT NOT NULL,
  status      TEXT NOT NULL DEFAULT 'pending'
              CHECK (status IN ('pending','approved','rejected','posted','failed')),
  source      TEXT DEFAULT 'api'
              CHECK (source IN ('api', 'rss', 'manual', 'scheduled')),
  li_post_id  TEXT,
  posted_at   TIMESTAMPTZ,
  created_at  TIMESTAMPTZ DEFAULT now()
);

-- ── Analytics ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS analytics (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  post_id       UUID NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  impressions   INT DEFAULT 0,
  likes         INT DEFAULT 0,
  comments      INT DEFAULT 0,
  shares        INT DEFAULT 0,
  clicks        INT DEFAULT 0,
  engagement_r  FLOAT GENERATED ALWAYS AS (
                  CASE WHEN impressions > 0
                  THEN (likes + comments + shares + clicks)::FLOAT / impressions
                  ELSE 0 END
                ) STORED,
  fetched_at    TIMESTAMPTZ DEFAULT now()
);

-- ── Topic dedup memory ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS used_topics (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  topic_hash  TEXT UNIQUE NOT NULL,
  topic       TEXT NOT NULL,
  used_at     TIMESTAMPTZ DEFAULT now()
);

-- ── Indexes ───────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_posts_status     ON posts(status);
CREATE INDEX IF NOT EXISTS idx_posts_user       ON posts(user_id);
CREATE INDEX IF NOT EXISTS idx_posts_created    ON posts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_analytics_post   ON analytics(post_id);
CREATE INDEX IF NOT EXISTS idx_used_topics_hash ON used_topics(topic_hash);

-- ── Row Level Security ────────────────────────────────────────
ALTER TABLE posts        ENABLE ROW LEVEL SECURITY;
ALTER TABLE analytics    ENABLE ROW LEVEL SECURITY;
ALTER TABLE used_topics  ENABLE ROW LEVEL SECURITY;

-- Public read for service role (n8n / FastAPI use service key)
CREATE POLICY "service_all_posts"     ON posts        FOR ALL USING (true);
CREATE POLICY "service_all_analytics" ON analytics    FOR ALL USING (true);
CREATE POLICY "service_all_topics"    ON used_topics  FOR ALL USING (true);

-- ── Realtime (for Streamlit live updates) ─────────────────────
ALTER PUBLICATION supabase_realtime ADD TABLE posts;
