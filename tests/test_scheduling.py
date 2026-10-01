"""排期互斥：窑炉时段不能重叠；点火时窑炉不能被占用。"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from base import ServiceTestCase
from pottery.services import DomainError


class TestScheduling(ServiceTestCase):
    def test_overlap_rejected(self):
        self.make_batch(start=self.now, end=self.now + timedelta(hours=9), name="批次A")
        with self.assertRaises(DomainError) as ctx:
            self.make_batch(start=self.now + timedelta(hours=3),
                            end=self.now + timedelta(hours=5), name="批次B")
        self.assertIn("时段冲突", str(ctx.exception))

    def test_adjacent_allowed(self):
        self.make_batch(start=self.now, end=self.now + timedelta(hours=9), name="批次A")
        # 首尾相接不算重叠
        bid = self.make_batch(start=self.now + timedelta(hours=9),
                              end=self.now + timedelta(hours=12), name="批次B")
        self.assertIsInstance(bid, int)

    def test_different_kiln_allowed(self):
        self.make_batch(start=self.now, end=self.now + timedelta(hours=9), name="窑一批次")
        bid = self.make_batch(start=self.now, end=self.now + timedelta(hours=9),
                              kiln_id=self.kiln2_id, name="窑二批次")
        self.assertIsInstance(bid, int)

    def test_ignite_while_kiln_busy_rejected(self):
        work = self.qualify(self.make_work())
        b1 = self.make_batch(start=self.now, end=self.now + timedelta(hours=9), name="批次A")
        self.svc.add_work_to_batch(self.teacher_id, b1, work, 1)
        self.ignite_batch(b1)
        # 批次B排期不与A的计划重叠，但点火时窑炉仍被A占用
        b2 = self.make_batch(start=self.now + timedelta(hours=20),
                             end=self.now + timedelta(hours=26), name="批次B")
        work2 = self.qualify(self.make_work())
        self.svc.add_work_to_batch(self.teacher_id, b2, work2, 1)
        self.advance(hours=1)
        with self.assertRaises(DomainError) as ctx:
            self.ignite_batch(b2)
        self.assertIn("占用", str(ctx.exception))

    def test_ignite_locks_and_computes_endpoints(self):
        work = self.qualify(self.make_work())
        batch = self.make_batch()
        self.svc.add_work_to_batch(self.teacher_id, batch, work, 1)
        self.ignite_batch(batch)
        detail = self.svc.batch_detail(batch)
        self.assertEqual(detail["batch"]["status"], "firing")
        self.assertIsNotNone(detail["batch"]["firing_end_at"])
        self.assertIsNotNone(detail["batch"]["cooled_at"])
        # 点火后锁定：不能装窑、不能改程序
        work2 = self.qualify(self.make_work())
        with self.assertRaises(DomainError):
            self.svc.add_work_to_batch(self.teacher_id, batch, work2, 1)
        with self.assertRaises(DomainError):
            self.svc.change_program(self.teacher_id, batch, self.program_id)

    def test_empty_batch_cannot_ignite(self):
        batch = self.make_batch()
        with self.assertRaises(DomainError):
            self.ignite_batch(batch)


if __name__ == "__main__":
    import unittest
    unittest.main()
