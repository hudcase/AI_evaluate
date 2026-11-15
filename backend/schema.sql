-- schema.sql — 9 张表
--
-- 与 docs/架构设计.md 的数据模型一一对应：
--   courses        M1 课程与目标（目标以 JSON 存，因为一条目标没有独立生命周期）
--   sessions       M1 场次
--   media_assets   M2 媒资（原档与课件）
--   ai_tasks       M3/M4 异步任务（预处理、评分），产物写 result_json
--   ai_calls       M4 每一次模型调用的记账
--   observations   M5 每场次每指标的观测值（含空值项，空值也是结论）
--   indicator_config M5 指标配置（按 config_version 多版本共存，不覆盖）
--   evaluations    M6 评价快照（只增不改，用于复算比对与申诉）
--   audit          所有写操作的留痕
--
-- 约定：
-- * 一切时间存 ISO 8601 带时区的字符串，排序即时间序（同城同偏移）
-- * 可空列一律允许 NULL，"没有数据"与"数据是 0"必须能区分
-- * 物理删除只发生在媒资文件上；表内一律逻辑删除（deleted_at）

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS courses (
  id               TEXT PRIMARY KEY,
  title            TEXT NOT NULL,
  expected_students INTEGER NOT NULL DEFAULT 0,
  goals_json       TEXT NOT NULL DEFAULT '[]',
  created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  id               TEXT PRIMARY KEY,
  course_id        TEXT NOT NULL REFERENCES courses(id),
  title            TEXT NOT NULL,
  scenario         TEXT NOT NULL CHECK (scenario IN ('theory','seminar','practical')),
  consent_confirmed INTEGER NOT NULL DEFAULT 0,
  teacher          TEXT,
  room             TEXT,
  date             TEXT NOT NULL,
  start            TEXT NOT NULL,
  duration_min     INTEGER NOT NULL DEFAULT 90,
  students         INTEGER NOT NULL DEFAULT 0,
  -- status 是"对外的评价状态"，stage 是"流水线走到哪"
  status           TEXT NOT NULL DEFAULT 'created'
                   CHECK (status IN ('created','processing','ok','divergent','insufficient')),
  stage            TEXT NOT NULL DEFAULT 'created',
  created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_course ON sessions(course_id);

CREATE TABLE IF NOT EXISTS media_assets (
  id             TEXT PRIMARY KEY,
  session_id     TEXT NOT NULL REFERENCES sessions(id),
  type           TEXT NOT NULL CHECK (type IN ('video','audio','slides','goals')),
  slot           TEXT,
  name           TEXT NOT NULL,
  path           TEXT,                      -- 落盘路径；未落盘（仅登记）为 NULL
  bytes          INTEGER NOT NULL DEFAULT 0,
  sha256         TEXT,
  duration_s     REAL,
  probe_json     TEXT NOT NULL DEFAULT '{}',
  retention_days INTEGER,
  status         TEXT NOT NULL DEFAULT 'ok',
  created_at     TEXT NOT NULL,
  deleted_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_media_session ON media_assets(session_id, deleted_at);
CREATE INDEX IF NOT EXISTS idx_media_sha ON media_assets(sha256);

CREATE TABLE IF NOT EXISTS ai_tasks (
  id          TEXT PRIMARY KEY,
  session_id  TEXT NOT NULL REFERENCES sessions(id),
  kind        TEXT NOT NULL,                -- preprocess | score | report
  status      TEXT NOT NULL DEFAULT 'queued'
              CHECK (status IN ('queued','running','succeeded','failed','canceled')),
  progress    REAL NOT NULL DEFAULT 0,
  stage       TEXT,
  error       TEXT,
  result_json TEXT NOT NULL DEFAULT '{}',   -- 流水线产物：gates / assets / stages
  started_at  TEXT,
  finished_at TEXT,
  created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_session ON ai_tasks(session_id, kind, status);

CREATE TABLE IF NOT EXISTS ai_calls (
  id             TEXT PRIMARY KEY,
  session_id     TEXT,
  capability     TEXT NOT NULL,             -- asr | ocr | embed | llm | vlm
  provider       TEXT NOT NULL,
  model_version  TEXT NOT NULL,             -- 缺失即拒，写库时强校验
  prompt_version TEXT NOT NULL,
  input_hash     TEXT,
  tokens_in      INTEGER NOT NULL DEFAULT 0,
  tokens_out     INTEGER NOT NULL DEFAULT 0,
  latency_ms     INTEGER NOT NULL DEFAULT 0,
  cost           REAL NOT NULL DEFAULT 0,
  cached         INTEGER NOT NULL DEFAULT 0,
  simulated      INTEGER NOT NULL DEFAULT 0, -- 1 = 桩模型产出，不是真实推理
  response_json  TEXT,                      -- 缓存体：命中时直接回放，不重复计费
  at             TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_calls_session ON ai_calls(session_id, at);
CREATE INDEX IF NOT EXISTS idx_calls_hash ON ai_calls(input_hash, capability);

CREATE TABLE IF NOT EXISTS observations (
  id             TEXT PRIMARY KEY,
  session_id     TEXT NOT NULL REFERENCES sessions(id),
  code           TEXT NOT NULL,
  raw_value      REAL,                      -- 允许 NULL：空值是结论，不是缺失
  denominator    REAL,
  unit           TEXT,
  confidence     REAL,
  evidence_t     REAL,                      -- 相对课程起点的秒数
  source_track_json TEXT NOT NULL DEFAULT '[]',
  note           TEXT,
  empty_reason   TEXT,
  model_version  TEXT,
  score          REAL,                      -- 服务端按量尺算出，客户端不得提交
  series_json    TEXT,                      -- 仅 VB1：逐分钟时序
  created_at     TEXT NOT NULL,
  updated_at     TEXT NOT NULL,
  UNIQUE (session_id, code)
);
CREATE INDEX IF NOT EXISTS idx_obs_session ON observations(session_id);

CREATE TABLE IF NOT EXISTS indicator_config (
  config_version TEXT NOT NULL,
  code           TEXT NOT NULL,
  name           TEXT NOT NULL,
  tier           TEXT NOT NULL,             -- audio | video
  domain         TEXT NOT NULL,             -- tm ts tb ss st gate listed
  domain_name    TEXT NOT NULL,
  domain_weight  REAL,
  weight         REAL,                      -- 不计分项为 NULL
  direction      TEXT NOT NULL,             -- inc reverse interval level combo gate listed
  a REAL, b REAL, c REAL, d REAL,
  unit           TEXT,
  denominator_rule TEXT,
  scored         INTEGER NOT NULL DEFAULT 1,
  published_at   TEXT NOT NULL,
  PRIMARY KEY (config_version, code)
);

CREATE TABLE IF NOT EXISTS evaluations (
  id               TEXT PRIMARY KEY,
  session_id       TEXT NOT NULL REFERENCES sessions(id),
  config_version   TEXT NOT NULL,
  audio_json       TEXT NOT NULL,
  video_json       TEXT NOT NULL,
  consistency_json TEXT NOT NULL,
  flags_json       TEXT NOT NULL DEFAULT '[]',
  missing_json     TEXT NOT NULL DEFAULT '[]',
  short_board_json TEXT NOT NULL DEFAULT '[]',
  composite        REAL,                    -- 恒为 NULL，保留列只为显式表达"不合成"
  computed_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eval_session ON evaluations(session_id, computed_at);

CREATE TABLE IF NOT EXISTS audit (
  id        TEXT PRIMARY KEY,
  action    TEXT NOT NULL,
  object_id TEXT,
  actor     TEXT NOT NULL DEFAULT 'system',
  detail_json TEXT NOT NULL DEFAULT '{}',
  at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_at ON audit(at DESC);
