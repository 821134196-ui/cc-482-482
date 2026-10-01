"""作品唯一：同一作品不能加入两个未结束批次；补烧后可进入新批次。"""
import os
import sys
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from base import ServiceTestCase
from pottery.services import DomainError


class TestUniqueness(ServiceTestCase):
    def test_work_in_two_active_batches_rejected(self):
        work = self.qualify(self.make_work())
        b1 = self.make_batch(name="批次A")
        b2 = self.make_batch(kiln_id=self.kiln2_id, name="批次B")  # 不同窑也算
        self.svc.add_work_to_batch(self.teacher_id, b1, work, 1)
        with self.assertRaises(DomainError) as ctx:
            self.svc.add_work_to_batch(self.teacher_id, b2, work, 1)
        self.assertIn("未结束批次", str(ctx.exception))

    def test_same_batch_duplicate_rejected(self):
        work = self.qualify(self.make_work())
        batch = self.make_batch()
        self.svc.add_work_to_batch(self.teacher_id, batch, work, 1)
        with self.assertRaises(DomainError):
            self.svc.add_work_to_batch(self.teacher_id, batch, work, 2)

    def test_rejoin_after_refire(self):
        """裂损→补烧→可加入新批次；原批次未结束时不行。"""
        work = self.qualify(self.make_work())
        b1 = self.make_batch()
        self.svc.add_work_to_batch(self.teacher_id, b1, work, 1)
        self.ignite_batch(b1)
        self.advance(hours=9)
        self.svc.open_kiln(self.teacher_id, b1)
        item_id = self.svc.batch_detail(b1)["items"][0]["item_id"]
        self.svc.record_inventory(self.teacher_id, b1, {item_id: ("cracked", "腹部裂纹")})
        # 补烧必须引用原作品与失败原因
        with self.assertRaises(DomainError):
            self.svc.create_refire(self.teacher_id, work, "")
        refire_id = self.svc.create_refire(self.teacher_id, work, "釉烧后腹部开裂")
        self.assertIsInstance(refire_id, int)
        # 原批次已开窑结束，作品可进入新批次
        b2 = self.make_batch(start=self.now + timedelta(hours=1),
                             end=self.now + timedelta(hours=10), name="补烧批次")
        self.svc.add_work_to_batch(self.teacher_id, b2, work, 1)
        refire = [r for r in self.svc.list_refires() if r["work_id"] == work][0]
        self.assertEqual(refire["status"], "scheduled")
        self.assertEqual(refire["new_batch_name"], "补烧批次")
        # 补烧批次烧制完成 → 补烧闭环
        self.ignite_batch(b2)
        self.advance(hours=9)
        self.svc.open_kiln(self.teacher_id, b2)
        item2 = self.svc.batch_detail(b2)["items"][0]["item_id"]
        self.svc.record_inventory(self.teacher_id, b2, {item2: ("ok", "")})
        refire = [r for r in self.svc.list_refires() if r["work_id"] == work][0]
        self.assertEqual(refire["status"], "done")
        self.assertEqual(self.svc.work_chain(work)["work"]["status"], "completed")


if __name__ == "__main__":
    import unittest
    unittest.main()
