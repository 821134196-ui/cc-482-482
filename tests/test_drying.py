"""干燥确认：不足时拒绝并留痕；达标后教师确认；标签脱落留痕。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from base import ServiceTestCase
from pottery.services import DomainError


class TestDrying(ServiceTestCase):
    def test_early_confirm_rejected_and_logged(self):
        work = self.make_work(drying_hours=48.0, started_hours_ago=5.0)
        with self.assertRaises(DomainError) as ctx:
            self.svc.confirm_drying(self.teacher_id, work)
        self.assertIn("干燥时间不足", str(ctx.exception))
        self.assertIn("insufficient_drying", self.incident_types(work_id=work))
        # 状态仍为干燥中
        self.assertEqual(self.svc.work_chain(work)["work"]["status"], "drying")

    def test_confirm_after_required_hours(self):
        work = self.make_work(drying_hours=24.0, started_hours_ago=30.0)
        self.svc.confirm_drying(self.teacher_id, work)
        chain = self.svc.work_chain(work)
        self.assertEqual(chain["work"]["status"], "dry_qualified")
        self.assertIsNotNone(chain["work"]["drying_confirmed_at"])

    def test_drying_queue_progress(self):
        ready = self.make_work(drying_hours=24.0, started_hours_ago=30.0)
        not_ready = self.make_work(drying_hours=48.0, started_hours_ago=6.0)
        queue = {q["id"]: q for q in self.svc.drying_queue()}
        self.assertTrue(queue[ready]["ready"])
        self.assertFalse(queue[not_ready]["ready"])
        self.assertAlmostEqual(queue[not_ready]["remaining_hours"], 42.0, places=1)

    def test_label_detached_logged(self):
        work = self.make_work()
        self.svc.report_label_detached(self.teacher_id, work)
        chain = self.svc.work_chain(work)
        self.assertEqual(chain["work"]["label_detached"], 1)
        self.assertIn("label_detached", self.incident_types(work_id=work))


if __name__ == "__main__":
    import unittest
    unittest.main()
