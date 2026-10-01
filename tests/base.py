"""测试基座：内存级临时库 + 可控时钟 + 最小夹具数据。"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pottery.domain import iso
from pottery.services import PotteryService

# 程序：25→500°C @300°C/h（95 分钟）+ 保温 30 分钟 ≈ 125 分钟
SEGMENTS = [{"target": 500, "rate": 300}, {"hold": 30}]


class ServiceTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pottery-test-")
        self.now = datetime(2026, 9, 30, 8, 0, 0)
        self.svc = PotteryService(os.path.join(self.tmp, "test.db"),
                                  photos_dir=os.path.join(self.tmp, "photos"),
                                  clock=lambda: self.now)
        self._fixtures()

    def tearDown(self):
        self.svc.close()
        shutil.rmtree(self.tmp, ignore_errors=True)

    def advance(self, **kwargs):
        """推进可控时钟。"""
        self.now = self.now + timedelta(**kwargs)
        self.svc.tick()

    def _fixtures(self):
        c = self.svc.conn
        c.execute("INSERT INTO users (username, display_name, role) VALUES ('admin', '管理员', 'admin')")
        c.execute("INSERT INTO users (username, display_name, role) VALUES ('t1', '教师甲', 'teacher')")
        c.execute("INSERT INTO users (username, display_name, role) VALUES ('s1', '学生A01', 'student')")
        c.execute("INSERT INTO classes (name) VALUES ('三(1)班')")
        c.execute("INSERT INTO students (anon_code, class_id, user_id) VALUES ('A01', 1, 3)")
        c.execute("INSERT INTO clays (name) VALUES ('白瓷泥')")
        c.execute("INSERT INTO glazes (name, color_hex) VALUES ('透明釉', '#cccccc')")   # 1
        c.execute("INSERT INTO glazes (name, color_hex) VALUES ('窑变橙', '#e2631e')")   # 2
        c.execute("INSERT INTO glazes (name, color_hex) VALUES ('翠绿釉', '#3e9c6c')")   # 3
        c.execute("INSERT INTO glaze_conflicts (glaze_a, glaze_b, reason) VALUES (2, 3, '相冲')")
        # 窑炉：2 层、净高 20cm、每层 4 工位、冷却 6h
        c.execute("INSERT INTO kilns (name, shelf_count, shelf_diameter_cm,"
                  " shelf_clearance_cm, shelf_slots, cooling_hours)"
                  " VALUES ('测试窑', 2, 45, 20, 4, 6)")
        c.execute("INSERT INTO kilns (name, shelf_count, shelf_diameter_cm,"
                  " shelf_clearance_cm, shelf_slots, cooling_hours)"
                  " VALUES ('二号测试窑', 2, 45, 20, 4, 6)")
        c.execute("INSERT INTO programs (name, kind, segments) VALUES ('素烧测试', 'bisque', ?)",
                  (json.dumps(SEGMENTS),))
        c.commit()
        self.admin_id, self.teacher_id, self.student_id = 1, 2, 3
        self.kiln_id, self.kiln2_id, self.program_id = 1, 2, 1

    # ------------------------------------------------------------ 工具
    def make_work(self, glaze_id=1, height=10.0, drying_hours=24.0, started_hours_ago=48.0):
        """登记一件作品并（默认）让干燥时间达标。"""
        work_id = self.svc.register_work(
            self.teacher_id, 1, 1, glaze_id, 10, 10, height, drying_hours)
        self.svc.conn.execute(
            "UPDATE works SET drying_started_at = ? WHERE id = ?",
            (iso(self.now - timedelta(hours=started_hours_ago)), work_id))
        self.svc.conn.commit()
        return work_id

    def qualify(self, work_id):
        self.svc.confirm_drying(self.teacher_id, work_id)
        return work_id

    def make_batch(self, start=None, end=None, kiln_id=None, name="测试批次"):
        start = start or self.now
        end = end or (start + timedelta(hours=9))
        return self.svc.schedule_batch(self.teacher_id, kiln_id or self.kiln_id,
                                       self.program_id, name, "bisque", start, end)

    def ignite_batch(self, batch_id):
        self.svc.ignite(self.admin_id, batch_id)

    def incident_types(self, work_id=None, batch_id=None):
        sql = "SELECT type FROM incidents WHERE 1=1"
        args = []
        if work_id is not None:
            sql += " AND work_id = ?"
            args.append(work_id)
        if batch_id is not None:
            sql += " AND batch_id = ?"
            args.append(batch_id)
        return [r["type"] for r in self.svc.conn.execute(sql, args).fetchall()]
