"""权限边界：学生只读；教师可排期装窑但不能点火/停电/异常开窑；管理员全权。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from base import ServiceTestCase
from pottery.services import PermissionDenied


class TestPermissions(ServiceTestCase):
    def _ready_batch(self):
        work = self.qualify(self.make_work())
        batch = self.make_batch()
        self.svc.add_work_to_batch(self.teacher_id, batch, work, 1)
        return batch, work

    def test_student_cannot_write(self):
        batch, work = self._ready_batch()
        s = self.student_id
        with self.assertRaises(PermissionDenied):
            self.svc.register_work(s, 1, 1, 1, 10, 10, 10)
        with self.assertRaises(PermissionDenied):
            self.svc.confirm_drying(s, self.make_work())
        with self.assertRaises(PermissionDenied):
            self.svc.schedule_batch(s, self.kiln_id, self.program_id, "x", "bisque",
                                    self.now, self.now.replace(hour=12))
        with self.assertRaises(PermissionDenied):
            self.svc.add_work_to_batch(s, batch, work, 1)
        with self.assertRaises(PermissionDenied):
            self.svc.ignite(s, batch)
        with self.assertRaises(PermissionDenied):
            self.svc.open_kiln(s, batch)
        with self.assertRaises(PermissionDenied):
            self.svc.report_label_detached(s, work)
        with self.assertRaises(PermissionDenied):
            self.svc.create_refire(s, work, "原因")

    def test_teacher_cannot_admin_ops(self):
        batch, _ = self._ready_batch()
        with self.assertRaises(PermissionDenied):
            self.svc.ignite(self.teacher_id, batch)          # 点火需管理员
        self.svc.ignite(self.admin_id, batch)
        with self.assertRaises(PermissionDenied):
            self.svc.report_power_outage(self.teacher_id, batch)  # 停电上报需管理员
        with self.assertRaises(PermissionDenied):
            self.svc.open_kiln(self.teacher_id, batch)       # 异常开窑需管理员

    def test_admin_full_ops(self):
        batch, _ = self._ready_batch()
        self.svc.ignite(self.admin_id, batch)
        self.svc.report_power_outage(self.admin_id, batch)
        self.assertEqual(self.svc.batch_detail(batch)["batch"]["status"], "interrupted")
        self.svc.restore_power(self.admin_id, batch)
        self.assertEqual(self.svc.batch_detail(batch)["batch"]["status"], "firing")
        self.assertIn("power_outage", self.incident_types(batch_id=batch))
        self.assertIn("power_restored", self.incident_types(batch_id=batch))

    def test_teacher_staff_ops_ok(self):
        # 教师：登记、确认干燥、排期、装窑、（冷却后）开窑、清点
        work = self.svc.register_work(self.teacher_id, 1, 1, 1, 10, 10, 10, 24)
        self.svc.conn.execute(
            "UPDATE works SET drying_started_at = ? WHERE id = ?",
            ("2026-09-28T08:00:00", work))
        self.svc.confirm_drying(self.teacher_id, work)
        batch = self.make_batch()
        self.svc.add_work_to_batch(self.teacher_id, batch, work, 1)
        self.svc.ignite(self.admin_id, batch)
        self.advance(hours=9)
        self.svc.open_kiln(self.teacher_id, batch)
        item_id = self.svc.batch_detail(batch)["items"][0]["item_id"]
        self.svc.record_inventory(self.teacher_id, batch, {item_id: ("ok", "")})
        self.assertEqual(self.svc.work_chain(work)["work"]["status"], "completed")


if __name__ == "__main__":
    import unittest
    unittest.main()
