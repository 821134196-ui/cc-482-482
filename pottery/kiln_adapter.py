"""模拟窑温适配器：按烧制程序曲线 + 冷却/停电衰减推算窑温读数。

真实环境中此处替换为热电偶/温控仪驱动；接口保持不变。
"""
from __future__ import annotations

import math
from datetime import datetime

from . import domain
from .services import (
    B_COOLING,
    B_FIRING,
    B_INTERRUPTED,
    PotteryService,
)


class SimulatedKilnAdapter:
    def __init__(self, service: PotteryService):
        self.svc = service

    # ------------------------------------------------------------ 内部
    def _segments(self, program_id: int):
        row = self.svc._one("SELECT segments FROM programs WHERE id = ?", (program_id,))
        return domain.parse_segments(row["segments"]) if row else []

    def _natural_temp(self, batch, at: datetime) -> tuple[float, str]:
        """不考虑停电时，at 时刻的程序温度。"""
        segments = self._segments(batch["program_id"])
        ignited = domain.parse_dt(batch["ignited_at"])
        firing_end = domain.parse_dt(batch["firing_end_at"])
        kiln = self.svc._one("SELECT * FROM kilns WHERE id = ?", (batch["kiln_id"],))
        if at < firing_end:
            elapsed = (at - ignited).total_seconds() / 60.0
            return domain.temp_at(segments, max(0.0, elapsed))
        end_temp = domain.program_final_temp(segments)
        cooling_min = (at - firing_end).total_seconds() / 60.0
        return domain.cooling_temp(end_temp, kiln["cooling_hours"], cooling_min), "冷却"

    def temp_for_batch(self, batch, at: datetime | None = None) -> tuple[float, str]:
        """指定批次的当前窑温与阶段（含停电衰减）。"""
        at = at or self.svc.now()
        if not batch["ignited_at"]:
            return domain.AMBIENT_C, "未点火"
        if batch["status"] == B_INTERRUPTED and batch["interrupted_at"]:
            interrupted_at = domain.parse_dt(batch["interrupted_at"])
            base, _ = self._natural_temp(batch, interrupted_at)
            decay_min = (at - interrupted_at).total_seconds() / 60.0
            return domain.outage_temp(base, max(0.0, decay_min)), "停电降温"
        temp, phase = self._natural_temp(batch, at)
        return temp, phase

    # ------------------------------------------------------------ 接口
    def read(self, kiln_id: int) -> dict:
        """读取窑炉当前温度（模拟传感器）。"""
        kiln = self.svc._one("SELECT * FROM kilns WHERE id = ?", (kiln_id,))
        if kiln is None:
            return {"ok": False, "error": "窑炉不存在"}
        batch = self.svc._one(
            "SELECT * FROM batches WHERE kiln_id = ? AND status IN (?, ?, ?)"
            " ORDER BY ignited_at DESC LIMIT 1",
            (kiln_id, B_FIRING, B_COOLING, B_INTERRUPTED))
        if batch is None:
            return {"ok": True, "kiln_id": kiln_id, "kiln": kiln["name"],
                    "temp": round(domain.AMBIENT_C, 1), "phase": "空闲",
                    "status": None, "batch_id": None, "batch_name": None,
                    "cooling_remaining_min": None}
        temp, phase = self.temp_for_batch(batch)
        # 传感器小波动，让读数更真实
        wobble = 1.5 * math.sin(self.svc.now().timestamp() / 37.0) if temp > 40 else 0.0
        cooling_remaining = None
        if batch["status"] == B_COOLING and batch["cooled_at"]:
            remain = (domain.parse_dt(batch["cooled_at"]) - self.svc.now()).total_seconds() / 60.0
            cooling_remaining = max(0.0, remain)
        return {"ok": True, "kiln_id": kiln_id, "kiln": kiln["name"],
                "temp": round(temp + wobble, 1), "phase": phase,
                "status": batch["status"], "batch_id": batch["id"],
                "batch_name": batch["name"],
                "cooling_remaining_min": cooling_remaining}
