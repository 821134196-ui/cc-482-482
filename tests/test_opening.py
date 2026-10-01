"""开窑阻断：未冷却开窑需管理员；异常开窑留痕；清点须先开窑。"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from base import ServiceTestCase
from pottery.services import DomainError, PermissionDenied


class TestOpening(ServiceTestCase):
    def _firing_batch(self):
        work = self.qualify(self.make_work())
        batch = self.make_batch()
        self.svc.add_work_to_batch(self.teacher_id, batch, work, 1)
        self.ignite_batch(batch)
        return batch, work

    def test_teacher_early_open_blocked(self):
        batch, _ = self._firing_batch()
        with self.assertRaises(PermissionDenied):
            self.svc.open_kiln(self.teacher_id, batch)

    def test_admin_early_open_logged(self):
        batch, _ = self._firing_batch()
        self.svc.open_kiln(self.admin_id, batch)
        detail = self.svc.batch_detail(batch)
        self.assertEqual(detail["batch"]["status"], "opened")
        self.assertEqual(detail["batch"]["early_open"], 1)
        self.assertIn("early_open", self.incident_types(batch_id=batch))

    def test_open_after_cooled_ok(self):
        batch, _ = self._firing_batch()
        self.advance(hours=9)  # 程序 125 分钟 + 冷却 6 小时
        detail = self.svc.batch_detail(batch)
        self.assertEqual(detail["batch"]["status"], "cooled")
        self.svc.open_kiln(self.teacher_id, batch)  # 教师可正常开窑
        detail = self.svc.batch_detail(batch)
        self.assertEqual(detail["batch"]["status"], "opened")
        self.assertEqual(detail["batch"]["early_open"], 0)

    def test_open_scheduled_rejected(self):
        batch = self.make_batch()
        with self.assertRaises(DomainError):
            self.svc.open_kiln(self.admin_id, batch)

    def test_inventory_requires_open(self):
        batch, work = self._firing_batch()
        item_id = self.svc.batch_detail(batch)["items"][0]["item_id"]
        with self.assertRaises(DomainError):
            self.svc.record_inventory(self.teacher_id, batch, {item_id: ("ok", "")})

    def test_inventory_records_crack_and_missing(self):
        w1 = self.qualify(self.make_work())
        w2 = self.qualify(self.make_work())
        w3 = self.qualify(self.make_work())
        batch = self.make_batch()
        self.svc.add_work_to_batch(self.teacher_id, batch, w1, 1)
        self.svc.add_work_to_batch(self.teacher_id, batch, w2, 1)
        self.svc.add_work_to_batch(self.teacher_id, batch, w3, 2)
        self.ignite_batch(batch)
        self.advance(hours=9)
        self.svc.open_kiln(self.teacher_id, batch)
        items = {i["work_id"]: i["item_id"] for i in self.svc.batch_detail(batch)["items"]}
        self.svc.record_inventory(self.teacher_id, batch, {
            items[w1]: ("ok", ""),
            items[w2]: ("cracked", "口沿裂纹"),
            items[w3]: ("missing", "清点未见"),
        })
        chain2 = self.svc.work_chain(w2)
        chain3 = self.svc.work_chain(w3)
        self.assertEqual(chain2["work"]["status"], "damaged")
        self.assertEqual(chain3["work"]["status"], "missing")
        self.assertIn("crack", self.incident_types(work_id=w2))
        self.assertIn("missing_piece", self.incident_types(work_id=w3))
        # 完好作品成为成品
        self.assertEqual(self.svc.work_chain(w1)["work"]["status"], "completed")


if __name__ == "__main__":
    import unittest
    unittest.main()
