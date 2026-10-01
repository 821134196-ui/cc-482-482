"""进程内调度任务：周期性推进批次状态（烧制→冷却→可开窑）。

干燥与冷却时点由服务层在点火/登记时计算并落库，本线程只负责到点推进。
"""
from __future__ import annotations

import threading


class Scheduler(threading.Thread):
    def __init__(self, service, interval: float = 1.0):
        super().__init__(daemon=True, name="pottery-scheduler")
        self.service = service
        self.interval = interval
        self._stop_event = threading.Event()

    def run(self):
        while not self._stop_event.is_set():
            try:
                self.service.tick()
            except Exception:
                pass  # 调度失败不影响主服务
            self._stop_event.wait(self.interval)

    def stop(self):
        self._stop_event.set()
