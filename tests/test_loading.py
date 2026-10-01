"""装载约束：超高、釉料相冲、容量、干燥资格、点火锁定。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from base import ServiceTestCase
from pottery.services import DomainError


class TestLoading(ServiceTestCase):
    def test_over_height_rejected_and_logged(self):
        tall = self.qualify(self.make_work(height=25.0))  # 层净高 20cm
        batch = self.make_batch()
        with self.assertRaises(DomainError) as ctx:
            self.svc.add_work_to_batch(self.teacher_id, batch, tall, 1)
        self.assertIn("超高", str(ctx.exception))
        self.assertIn("over_height", self.incident_types(work_id=tall))

    def test_glaze_conflict_rejected_and_logged(self):
        work_a = self.qualify(self.make_work(glaze_id=2))  # 窑变橙
        work_b = self.qualify(self.make_work(glaze_id=3))  # 翠绿釉（与窑变橙相冲）
        batch = self.make_batch()
        self.svc.add_work_to_batch(self.teacher_id, batch, work_a, 1)
        with self.assertRaises(DomainError) as ctx:
            self.svc.add_work_to_batch(self.teacher_id, batch, work_b, 1)
        self.assertIn("釉料相冲", str(ctx.exception))
        self.assertIn("glaze_conflict", self.incident_types(work_id=work_b))
        # 换一层则相容
        self.svc.add_work_to_batch(self.teacher_id, batch, work_b, 2)
        detail = self.svc.batch_detail(batch)
        self.assertEqual(len(detail["items"]), 2)

    def test_shelf_capacity(self):
        batch = self.make_batch()
        works = [self.qualify(self.make_work()) for _ in range(4)]
        for w in works:
            self.svc.add_work_to_batch(self.teacher_id, batch, w, 1)
        fifth = self.qualify(self.make_work())
        with self.assertRaises(DomainError) as ctx:
            self.svc.add_work_to_batch(self.teacher_id, batch, fifth, 1)
        self.assertIn("已满", str(ctx.exception))

    def test_unqualified_work_rejected(self):
        fresh = self.make_work(drying_hours=48.0, started_hours_ago=2.0)  # 仍在干燥
        batch = self.make_batch()
        with self.assertRaises(DomainError) as ctx:
            self.svc.add_work_to_batch(self.teacher_id, batch, fresh, 1)
        self.assertIn("干燥", str(ctx.exception))

    def test_invalid_shelf_rejected(self):
        work = self.qualify(self.make_work())
        batch = self.make_batch()
        with self.assertRaises(DomainError):
            self.svc.add_work_to_batch(self.teacher_id, batch, work, 99)

    def test_auto_assign_respects_constraints(self):
        ok1 = self.qualify(self.make_work(glaze_id=1))
        ok2 = self.qualify(self.make_work(glaze_id=2))
        conflict = self.qualify(self.make_work(glaze_id=3))  # 与 ok2 相冲，但可分不同层
        tall = self.qualify(self.make_work(height=30.0))     # 超高，必然失败
        batch = self.make_batch()
        result = self.svc.auto_assign(self.teacher_id, batch, [ok1, ok2, conflict, tall])
        placed_ids = {p["work_id"] for p in result["placed"]}
        self.assertIn(ok1, placed_ids)
        self.assertIn(ok2, placed_ids)
        self.assertIn(conflict, placed_ids)  # 自动分到另一层
        self.assertEqual([f["work_id"] for f in result["failed"]], [tall])
        # 相冲两件不在同一层
        detail = self.svc.batch_detail(batch)
        shelves = {i["work_id"]: i["shelf_no"] for i in detail["items"]}
        self.assertNotEqual(shelves[ok2], shelves[conflict])


if __name__ == "__main__":
    import unittest
    unittest.main()
