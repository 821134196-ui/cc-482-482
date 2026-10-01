'use strict';

const { DatabaseSync } = require('node:sqlite');

const SCHEMA = `
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin','teacher'))
);

CREATE TABLE IF NOT EXISTS tokens (
  token TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id)
);

CREATE TABLE IF NOT EXISTS classes (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS students (
  id INTEGER PRIMARY KEY,
  class_id INTEGER NOT NULL REFERENCES classes(id),
  code TEXT NOT NULL UNIQUE          -- 匿名代号，如 S3-01，不存真实姓名
);

CREATE TABLE IF NOT EXISTS clays (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  dry_hours_base REAL NOT NULL,      -- 基础自然干燥时长（小时）
  note TEXT
);

CREATE TABLE IF NOT EXISTS glazes (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  color_hex TEXT,
  note TEXT
);

-- 釉料相冲矩阵（无向，按小 id 在前存储）
CREATE TABLE IF NOT EXISTS glaze_conflicts (
  glaze_a INTEGER NOT NULL REFERENCES glazes(id),
  glaze_b INTEGER NOT NULL REFERENCES glazes(id),
  reason TEXT,
  PRIMARY KEY (glaze_a, glaze_b),
  CHECK (glaze_a < glaze_b)
);

CREATE TABLE IF NOT EXISTS works (
  id INTEGER PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,          -- 作品代号 W-0001
  student_id INTEGER NOT NULL REFERENCES students(id),
  clay_id INTEGER NOT NULL REFERENCES clays(id),
  glaze_id INTEGER REFERENCES glazes(id),
  stage TEXT NOT NULL DEFAULT 'bisque' CHECK (stage IN ('bisque','glaze','done')),
  width_mm INTEGER NOT NULL,
  depth_mm INTEGER NOT NULL,
  height_mm INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'drying' CHECK (status IN
    ('drying','dry_qualified','scheduled','firing','cooling',
     'awaiting_glaze','finished','damaged','missing','refire_pending')),
  dry_required_hours REAL NOT NULL,
  dry_started_at TEXT NOT NULL,
  dry_due_at TEXT NOT NULL,           -- 进程内任务算出的干燥达标时点
  dry_confirmed_at TEXT,
  dry_confirmed_by TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kilns (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  shelf_count INTEGER NOT NULL,
  shelf_radius_mm INTEGER NOT NULL,   -- 圆形棚板半径（俯视示意用）
  shelf_gap_mm INTEGER NOT NULL,      -- 层间净高，超限即“装载超高”
  shelf_slot_capacity INTEGER NOT NULL DEFAULT 12,
  max_temp_c INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS programs (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL CHECK (kind IN ('bisque','glaze')),
  steps_json TEXT NOT NULL,           -- [{ramp:°C/h, target:°C, hold:min}]
  cool_rate_c_per_h REAL NOT NULL DEFAULT 100
);

CREATE TABLE IF NOT EXISTS batches (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  kiln_id INTEGER NOT NULL REFERENCES kilns(id),
  program_id INTEGER NOT NULL REFERENCES programs(id),
  kind TEXT NOT NULL CHECK (kind IN ('bisque','glaze')),
  scheduled_start TEXT NOT NULL,
  scheduled_end TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'scheduled' CHECK (status IN
    ('scheduled','loaded','firing','cooling','cooled','opened','closed','interrupted','cancelled')),
  ignited_at TEXT,
  ignited_by TEXT,
  firing_end_at TEXT,
  cooled_until TEXT,                  -- 完全冷却时点，此前开窑属“开窑过早”
  opened_at TEXT,
  opened_by TEXT,
  opened_early INTEGER NOT NULL DEFAULT 0,
  created_by TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS batch_items (
  id INTEGER PRIMARY KEY,
  batch_id INTEGER NOT NULL REFERENCES batches(id),
  work_id INTEGER NOT NULL REFERENCES works(id),
  shelf_no INTEGER,
  slot_angle_deg REAL,
  slot_radius_mm REAL,
  result TEXT NOT NULL DEFAULT 'pending' CHECK (result IN ('pending','intact','cracked','missing')),
  damage_note TEXT,
  UNIQUE (batch_id, work_id)
);
CREATE INDEX IF NOT EXISTS idx_items_work ON batch_items(work_id);
CREATE INDEX IF NOT EXISTS idx_items_batch ON batch_items(batch_id);

-- 补烧：必须引用原作品与失败原因
CREATE TABLE IF NOT EXISTS refires (
  id INTEGER PRIMARY KEY,
  work_id INTEGER NOT NULL REFERENCES works(id),
  source_batch_id INTEGER NOT NULL REFERENCES batches(id),
  reason TEXT NOT NULL,
  new_batch_id INTEGER REFERENCES batches(id),
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','scheduled','done')),
  created_by TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS photos (
  id INTEGER PRIMARY KEY,
  owner_type TEXT NOT NULL CHECK (owner_type IN ('batch','work')),
  owner_id INTEGER NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('loading','product')),
  path TEXT NOT NULL,
  uploaded_by TEXT,
  created_at TEXT NOT NULL
);

-- 留痕：异常与生命周期事件统一流水
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  entity_type TEXT NOT NULL,          -- work | batch | kiln
  entity_id INTEGER NOT NULL,
  type TEXT NOT NULL,                 -- label_lost / dry_insufficient / glaze_conflict / over_height
                                      -- / power_outage / early_open / cracked / missing / 生命周期事件
  detail TEXT,
  actor TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_entity ON events(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
`;

function openDb(path) {
  const db = new DatabaseSync(path);
  db.exec(SCHEMA);
  return db;
}

module.exports = { openDb };
