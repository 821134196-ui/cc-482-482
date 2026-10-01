"""SQLite 连接与表结构。作品全链路（登记→干燥→装窑→烧制→出窑→补烧）均落库。"""
from __future__ import annotations

import sqlite3

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'teacher', 'student'))
);

CREATE TABLE IF NOT EXISTS classes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    anon_code TEXT UNIQUE NOT NULL,          -- 匿名代号，不存真实姓名
    class_id INTEGER NOT NULL REFERENCES classes (id),
    user_id INTEGER UNIQUE REFERENCES users (id)
);

CREATE TABLE IF NOT EXISTS clays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    note TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS glazes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    color_hex TEXT NOT NULL DEFAULT '#999999',
    note TEXT NOT NULL DEFAULT ''
);

-- 釉料相容性：同层棚板上不允许出现的相冲釉色对
CREATE TABLE IF NOT EXISTS glaze_conflicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    glaze_a INTEGER NOT NULL REFERENCES glazes (id),
    glaze_b INTEGER NOT NULL REFERENCES glazes (id),
    reason TEXT NOT NULL DEFAULT '',
    UNIQUE (glaze_a, glaze_b)
);

CREATE TABLE IF NOT EXISTS works (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,               -- 作品代号
    student_id INTEGER NOT NULL REFERENCES students (id),
    clay_id INTEGER NOT NULL REFERENCES clays (id),
    glaze_id INTEGER NOT NULL REFERENCES glazes (id),
    width_cm REAL NOT NULL,
    depth_cm REAL NOT NULL,
    height_cm REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'drying',
    drying_started_at TEXT NOT NULL,
    drying_required_hours REAL NOT NULL DEFAULT 48,
    drying_confirmed_at TEXT,
    drying_confirmed_by INTEGER REFERENCES users (id),
    label_detached INTEGER NOT NULL DEFAULT 0,   -- 标签脱落标记
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kilns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    shelf_count INTEGER NOT NULL,            -- 棚板层数
    shelf_diameter_cm REAL NOT NULL,         -- 圆形棚板直径
    shelf_clearance_cm REAL NOT NULL,        -- 每层净高（装载超高判定）
    shelf_slots INTEGER NOT NULL DEFAULT 12, -- 每层工位数
    cooling_hours REAL NOT NULL DEFAULT 12   -- 烧后冷却时长
);

CREATE TABLE IF NOT EXISTS programs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    kind TEXT NOT NULL DEFAULT 'bisque',     -- bisque 素烧 / glaze 釉烧
    segments TEXT NOT NULL                   -- JSON: [{"target":600,"rate":150},{"hold":30},...]
);

CREATE TABLE IF NOT EXISTS batches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kiln_id INTEGER NOT NULL REFERENCES kilns (id),
    program_id INTEGER NOT NULL REFERENCES programs (id),
    kind TEXT NOT NULL DEFAULT 'bisque',
    status TEXT NOT NULL DEFAULT 'scheduled',
    -- scheduled 已排期 / firing 烧制中 / cooling 冷却中 / cooled 待开窑
    -- / opened 已开窑 / interrupted 停电中断
    scheduled_start TEXT NOT NULL,
    scheduled_end TEXT NOT NULL,
    ignited_at TEXT,
    ignited_by INTEGER REFERENCES users (id),
    firing_end_at TEXT,                      -- 点火时按程序时长计算
    cooled_at TEXT,                          -- firing_end + 窑炉冷却时长
    interrupted_at TEXT,                     -- 停电时刻（恢复后顺延 firing_end/cooled）
    opened_at TEXT,
    opened_by INTEGER REFERENCES users (id),
    early_open INTEGER NOT NULL DEFAULT 0,   -- 异常开窑标记
    created_by INTEGER NOT NULL REFERENCES users (id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS batch_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id INTEGER NOT NULL REFERENCES batches (id),
    work_id INTEGER NOT NULL REFERENCES works (id),
    shelf_no INTEGER NOT NULL,               -- 棚板层号（1 起）
    slot_no INTEGER NOT NULL,                -- 层内工位号
    result TEXT,                             -- 出窑结果：ok / cracked / missing
    result_note TEXT NOT NULL DEFAULT '',
    UNIQUE (batch_id, work_id)
);

-- 异常留痕：标签脱落/干燥不足/釉料相冲/装载超高/停电/异常开窑/裂损/少件
CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    work_id INTEGER REFERENCES works (id),
    batch_id INTEGER REFERENCES batches (id),
    actor_id INTEGER REFERENCES users (id),
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                      -- loading 装窑 / finished 成品
    work_id INTEGER REFERENCES works (id),
    batch_id INTEGER REFERENCES batches (id),
    filename TEXT NOT NULL,
    uploaded_by INTEGER REFERENCES users (id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS refires (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    work_id INTEGER NOT NULL REFERENCES works (id),      -- 必须引用原作品
    source_batch_id INTEGER NOT NULL REFERENCES batches (id),
    reason TEXT NOT NULL,                                -- 必须填写失败原因
    status TEXT NOT NULL DEFAULT 'pending',              -- pending / scheduled / done
    new_batch_id INTEGER REFERENCES batches (id),
    created_by INTEGER NOT NULL REFERENCES users (id),
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_batch_items_work ON batch_items (work_id);
CREATE INDEX IF NOT EXISTS idx_batches_kiln ON batches (kiln_id, status);
CREATE INDEX IF NOT EXISTS idx_incidents_type ON incidents (type);
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
