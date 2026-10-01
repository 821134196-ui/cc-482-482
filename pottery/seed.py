"""种子数据：一条启动命令即可载入完整演示场景。

包含：班级与匿名学生、泥料、釉色与相冲对、两座窑炉、素烧/釉烧程序、
各状态作品，以及釉料相冲、装载超高、干燥不足、标签脱落、停电中断、
裂损补烧、少件等留痕样例。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from . import domain
from .photos import write_seed_photos
from .services import (
    B_FIRING,
    B_INTERRUPTED,
    B_OPENED,
    B_SCHEDULED,
    INC_CRACK,
    INC_DRYING,
    INC_GLAZE,
    INC_HEIGHT,
    INC_LABEL,
    INC_MISSING,
    INC_OUTAGE,
    WORK_COMPLETED,
    WORK_DAMAGED,
    WORK_DRYING,
    WORK_FIRING,
    WORK_MISSING,
    WORK_QUALIFIED,
    WORK_REFIRE,
    WORK_SCHEDULED,
    PotteryService,
)

BISQUE_SEGMENTS = [
    {"target": 200, "rate": 150},
    {"hold": 20},
    {"target": 500, "rate": 200},
    {"hold": 15},
    {"target": 900, "rate": 250},
    {"hold": 20},
]

GLAZE_SEGMENTS = [
    {"target": 250, "rate": 150},
    {"hold": 15},
    {"target": 700, "rate": 250},
    {"hold": 10},
    {"target": 1000, "rate": 200},
    {"target": 1180, "rate": 120},
    {"hold": 25},
]


def _iso(dt: datetime) -> str:
    return domain.iso(dt)


def seed_if_empty(svc: PotteryService) -> bool:
    """数据库为空时载入样例数据。返回是否执行了种子。"""
    if svc._one("SELECT COUNT(*) AS n FROM users")["n"] > 0:
        return False
    now = svc.now()
    conn = svc.conn
    with svc.lock, conn:
        _seed_users_students(conn)
        _seed_materials(conn)
        _seed_kilns_programs(conn)
        ids = _seed_works(conn, now)
        _seed_batches(conn, svc, now, ids)
        _seed_incidents(conn, now, ids)
        _seed_refire(conn, now, ids)
        _seed_photos(conn, svc, now, ids)
    return True


def _seed_users_students(conn):
    conn.execute("INSERT INTO users (username, display_name, role) VALUES ('admin', '周管理员', 'admin')")
    conn.execute("INSERT INTO users (username, display_name, role) VALUES ('wang', '王老师', 'teacher')")
    conn.execute("INSERT INTO users (username, display_name, role) VALUES ('li', '李老师', 'teacher')")
    classes = ["三(1)班", "三(2)班", "四(1)班"]
    for name in classes:
        conn.execute("INSERT INTO classes (name) VALUES (?)", (name,))
    # 匿名学生：只用代号，不出现真实姓名
    for i in range(1, 13):
        anon = f"A{i:02d}"
        class_id = (i - 1) // 4 + 1
        cur = conn.execute(
            "INSERT INTO users (username, display_name, role) VALUES (?, ?, 'student')",
            (f"s{i:02d}", f"学生 {anon}"))
        conn.execute(
            "INSERT INTO students (anon_code, class_id, user_id) VALUES (?, ?, ?)",
            (anon, class_id, cur.lastrowid))


def _seed_materials(conn):
    for name, note in [("红陶土", "可塑性好，适合低年级"),
                       ("白瓷泥", "细腻，适合上釉"),
                       ("粗陶泥", "颗粒感强，适合大件")]:
        conn.execute("INSERT INTO clays (name, note) VALUES (?, ?)", (name, note))
    glazes = [("透明釉", "#cfc9b8", "安全百搭"),
              ("天青釉", "#7fb3d5", "釉蓝色系"),
              ("窑变橙", "#e2631e", "窑火橙色系"),
              ("翠绿釉", "#3e9c6c", "铜绿色系"),
              ("铁红釉", "#a03427", "铁系发色")]
    for name, color, note in glazes:
        conn.execute("INSERT INTO glazes (name, color_hex, note) VALUES (?, ?, ?)",
                     (name, color, note))
    # 釉料相冲对（同层棚板禁止）
    conn.execute("INSERT INTO glaze_conflicts (glaze_a, glaze_b, reason) VALUES (3, 4, ?)",
                 ("高温下窑变橙与翠绿釉相互污染发色",))
    conn.execute("INSERT INTO glaze_conflicts (glaze_a, glaze_b, reason) VALUES (2, 5, ?)",
                 ("铁红釉挥发物会污染天青釉发色",))


def _seed_kilns_programs(conn):
    conn.execute(
        "INSERT INTO kilns (name, shelf_count, shelf_diameter_cm, shelf_clearance_cm,"
        " shelf_slots, cooling_hours) VALUES ('一号窑', 4, 60, 25, 12, 10)")
    conn.execute(
        "INSERT INTO kilns (name, shelf_count, shelf_diameter_cm, shelf_clearance_cm,"
        " shelf_slots, cooling_hours) VALUES ('二号窑', 3, 45, 18, 8, 8)")
    import json
    conn.execute(
        "INSERT INTO programs (name, kind, segments) VALUES ('素烧·900°C', 'bisque', ?)",
        (json.dumps(BISQUE_SEGMENTS),))
    conn.execute(
        "INSERT INTO programs (name, kind, segments) VALUES ('釉烧·1180°C', 'glaze', ?)",
        (json.dumps(GLAZE_SEGMENTS),))


def _seed_works(conn, now: datetime) -> dict:
    """作品：code -> id。状态覆盖干燥中/合格/已排/烧制中/成品/裂损/少件/待补烧。"""
    # (student_id, clay, glaze, w, d, h, status, 干燥开始于几小时前, 标签脱落)
    works = [
        (1,  2, 2, 12, 12, 15, WORK_COMPLETED, 120, 0),   # W001 天青瓶
        (2,  1, 3, 10, 10, 9,  WORK_COMPLETED, 120, 0),   # W002 窑变橙小碗
        (3,  3, 1, 14, 14, 20, WORK_FIRING,    96, 0),    # W003 今日素烧
        (4,  2, 4, 11, 11, 13, WORK_FIRING,    96, 0),    # W004 今日素烧
        (5,  1, 1, 9, 9, 12,   WORK_SCHEDULED, 80, 0),    # W005 明日批次
        (6,  2, 2, 13, 13, 10, WORK_SCHEDULED, 80, 0),    # W006 明日批次
        (7,  3, 5, 12, 12, 22, WORK_SCHEDULED, 80, 0),    # W007 明日批次
        (8,  2, 4, 10, 10, 14, WORK_SCHEDULED, 78, 0),    # W008 明日批次(翠绿)
        (9,  1, 3, 12, 12, 16, WORK_QUALIFIED, 76, 0),    # W009 待装窑(窑变橙)
        (10, 3, 1, 15, 15, 30, WORK_QUALIFIED, 74, 0),    # W010 待装窑(超高样品)
        (11, 2, 2, 8, 8, 10,   WORK_DRYING,    72, 0),    # W011 干燥达标可确认
        (12, 1, 1, 12, 12, 9,  WORK_DRYING,    96, 1),    # W012 标签脱落样例
        (1,  3, 4, 13, 13, 18, WORK_DRYING,    6, 0),     # W013 干燥不足样例
        (2,  2, 1, 9, 9, 11,   WORK_DRYING,    20, 0),    # W014 干燥中
        (3,  2, 2, 10, 10, 12, WORK_FIRING,    90, 0),    # W015 停电批次
        (4,  1, 5, 11, 11, 8,  WORK_FIRING,    90, 0),    # W016 停电批次
        (5,  2, 3, 12, 12, 15, WORK_REFIRE,    130, 0),   # W017 裂损→待补烧
        (6,  3, 1, 10, 10, 10, WORK_MISSING,   130, 0),   # W018 少件样例
    ]
    ids = {}
    for i, (stu, clay, glaze, w, d, h, status, hours_ago, label) in enumerate(works, start=1):
        code = f"W{i:03d}"
        started = now - timedelta(hours=hours_ago)
        confirmed = status in (WORK_QUALIFIED, WORK_SCHEDULED, WORK_FIRING,
                               WORK_COMPLETED, WORK_REFIRE, WORK_MISSING)
        cur = conn.execute(
            "INSERT INTO works (code, student_id, clay_id, glaze_id, width_cm, depth_cm,"
            " height_cm, status, drying_started_at, drying_required_hours,"
            " drying_confirmed_at, drying_confirmed_by, label_detached, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 48, ?, ?, ?, ?)",
            (code, stu, clay, glaze, w, d, h, status, _iso(started),
             _iso(started + timedelta(hours=50)) if confirmed else None,
             2 if confirmed else None, label, _iso(started)))
        ids[code] = cur.lastrowid
    return ids


def _seed_batches(conn, svc: PotteryService, now: datetime, ids: dict):
    bisque_hours = domain.program_duration_minutes(BISQUE_SEGMENTS) / 60.0
    glaze_hours = domain.program_duration_minutes(GLAZE_SEGMENTS) / 60.0

    # B1 明日素烧（一号窑，已排期，装窑中）
    b1_start = (now + timedelta(days=1)).replace(hour=19, minute=0, second=0, microsecond=0)
    b1_end = b1_start + timedelta(hours=bisque_hours + 10)
    cur = conn.execute(
        "INSERT INTO batches (name, kiln_id, program_id, kind, status, scheduled_start,"
        " scheduled_end, created_by, created_at)"
        " VALUES ('一号窑·素烧·明日', 1, 1, 'bisque', ?, ?, ?, 2, ?)",
        (B_SCHEDULED, _iso(b1_start), _iso(b1_end), _iso(now - timedelta(hours=5))))
    b1 = cur.lastrowid
    for code, shelf, slot in [("W005", 1, 1), ("W006", 1, 2), ("W008", 1, 3), ("W007", 2, 1)]:
        conn.execute("INSERT INTO batch_items (batch_id, work_id, shelf_no, slot_no)"
                     " VALUES (?, ?, ?, ?)", (b1, ids[code], shelf, slot))

    # B2 今日素烧（一号窑，烧制中：2 小时前点火）
    ignited2 = now - timedelta(hours=2)
    firing_end2 = ignited2 + timedelta(hours=bisque_hours)
    cooled2 = firing_end2 + timedelta(hours=10)
    cur = conn.execute(
        "INSERT INTO batches (name, kiln_id, program_id, kind, status, scheduled_start,"
        " scheduled_end, ignited_at, ignited_by, firing_end_at, cooled_at, created_by, created_at)"
        " VALUES ('一号窑·素烧·今日', 1, 1, 'bisque', ?, ?, ?, ?, 1, ?, ?, 2, ?)",
        (B_FIRING, _iso(ignited2 - timedelta(minutes=30)), _iso(cooled2),
         _iso(ignited2), _iso(firing_end2), _iso(cooled2), _iso(now - timedelta(days=1))))
    b2 = cur.lastrowid
    for code, shelf, slot in [("W003", 1, 1), ("W004", 2, 1)]:
        conn.execute("INSERT INTO batch_items (batch_id, work_id, shelf_no, slot_no)"
                     " VALUES (?, ?, ?, ?)", (b2, ids[code], shelf, slot))

    # B3 停电中断样例（二号窑，釉烧，40 分钟前停电）
    ignited3 = now - timedelta(hours=3)
    firing_end3 = ignited3 + timedelta(hours=glaze_hours)
    cooled3 = firing_end3 + timedelta(hours=8)
    cur = conn.execute(
        "INSERT INTO batches (name, kiln_id, program_id, kind, status, scheduled_start,"
        " scheduled_end, ignited_at, ignited_by, firing_end_at, cooled_at, interrupted_at,"
        " created_by, created_at)"
        " VALUES ('二号窑·釉烧·第3批', 2, 2, 'glaze', ?, ?, ?, ?, 1, ?, ?, ?, 2, ?)",
        (B_INTERRUPTED, _iso(ignited3 - timedelta(minutes=30)), _iso(cooled3),
         _iso(ignited3), _iso(firing_end3), _iso(cooled3),
         _iso(now - timedelta(minutes=40)), _iso(now - timedelta(days=1))))
    b3 = cur.lastrowid
    for code, shelf, slot in [("W015", 1, 1), ("W016", 2, 1)]:
        conn.execute("INSERT INTO batch_items (batch_id, work_id, shelf_no, slot_no)"
                     " VALUES (?, ?, ?, ?)", (b3, ids[code], shelf, slot))

    # B4 已开窑批次（二号窑，釉烧，含裂损与少件）
    ignited4 = now - timedelta(days=3)
    firing_end4 = ignited4 + timedelta(hours=glaze_hours)
    cooled4 = firing_end4 + timedelta(hours=8)
    opened4 = cooled4 + timedelta(hours=2)
    cur = conn.execute(
        "INSERT INTO batches (name, kiln_id, program_id, kind, status, scheduled_start,"
        " scheduled_end, ignited_at, ignited_by, firing_end_at, cooled_at, opened_at,"
        " opened_by, created_by, created_at)"
        " VALUES ('二号窑·釉烧·第2批', 2, 2, 'glaze', ?, ?, ?, ?, 1, ?, ?, ?, 1, 2, ?)",
        (B_OPENED, _iso(ignited4 - timedelta(minutes=30)), _iso(cooled4),
         _iso(ignited4), _iso(firing_end4), _iso(cooled4), _iso(opened4),
         _iso(now - timedelta(days=4))))
    b4 = cur.lastrowid
    items = [("W001", 1, 1, "ok", ""), ("W002", 1, 2, "ok", ""),
             ("W017", 2, 1, "cracked", "腹部纵向裂纹"), ("W018", 2, 2, "missing", "清点时未发现")]
    for code, shelf, slot, result, note in items:
        conn.execute(
            "INSERT INTO batch_items (batch_id, work_id, shelf_no, slot_no, result, result_note)"
            " VALUES (?, ?, ?, ?, ?, ?)", (b4, ids[code], shelf, slot, result, note))
    return {"b1": b1, "b2": b2, "b3": b3, "b4": b4}


def _seed_incidents(conn, now: datetime, ids: dict):
    batches = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM batches")}
    b1, b3, b4 = batches["一号窑·素烧·明日"], batches["二号窑·釉烧·第3批"], batches["二号窑·釉烧·第2批"]
    rows = [
        (INC_LABEL, ids["W012"], None, 2, "作品 W012 标签脱落，已按代号重新登记", 26),
        (INC_DRYING, ids["W013"], None, 3, "已干燥 6.0h / 要求 48h", 2),
        (INC_GLAZE, ids["W009"], b1, 3,
         "作品 W009 与同层 W008 釉料相冲（窑变橙 × 翠绿釉：高温下相互污染发色）", 20),
        (INC_HEIGHT, ids["W010"], b1, 3,
         "作品 W010 高 30cm，超过 一号窑 层净高 25cm", 19),
        (INC_OUTAGE, None, b3, 1, "市电中断，等待供电恢复", 0.7),
        (INC_CRACK, ids["W017"], b4, 2, "出窑清点：作品 W017 裂损。腹部纵向裂纹", 46),
        (INC_MISSING, ids["W018"], b4, 2, "出窑清点：作品 W018 少件。清点时未发现", 46),
    ]
    for inc_type, work_id, batch_id, actor, detail, hours_ago in rows:
        conn.execute(
            "INSERT INTO incidents (type, work_id, batch_id, actor_id, detail, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (inc_type, work_id, batch_id, actor, detail,
             _iso(now - timedelta(hours=hours_ago))))


def _seed_refire(conn, now: datetime, ids: dict):
    source = conn.execute(
        "SELECT batch_id FROM batch_items WHERE work_id = ? AND result = 'cracked'",
        (ids["W017"],)).fetchone()
    conn.execute(
        "INSERT INTO refires (work_id, source_batch_id, reason, status, created_by, created_at)"
        " VALUES (?, ?, ?, 'pending', 2, ?)",
        (ids["W017"], source["batch_id"], "釉烧后腹部开裂，需低温补烧修复",
         _iso(now - timedelta(hours=45))))


def _seed_photos(conn, svc: PotteryService, now: datetime, ids: dict):
    files = write_seed_photos(svc.photos_dir)
    batches = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM batches")}
    rows = [
        ("loading", None, batches["一号窑·素烧·今日"], files["loading_b2"], 2, 1.5),
        ("loading", None, batches["二号窑·釉烧·第2批"], files["loading_b4"], 2, 74),
        ("finished", ids["W001"], None, files["finished_w01"], 2, 45),
        ("finished", ids["W002"], None, files["finished_w02"], 2, 45),
    ]
    for kind, work_id, batch_id, filename, uploader, hours_ago in rows:
        conn.execute(
            "INSERT INTO photos (kind, work_id, batch_id, filename, uploaded_by, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (kind, work_id, batch_id, filename, uploader,
             _iso(now - timedelta(hours=hours_ago))))
