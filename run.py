#!/usr/bin/env python3
"""一条本地启动命令：

    python3 run.py [--port 8000] [--data ./data]

自动完成：建库建表 → 载入样例数据（含釉料相冲、停电中断、补烧样例）
→ 启动进程内调度（干燥/冷却时点推进）→ 启动 Web 服务。
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pottery.scheduler import Scheduler
from pottery.seed import seed_if_empty
from pottery.services import PotteryService
from pottery.web import serve


def main():
    parser = argparse.ArgumentParser(description="小学陶艺教室窑炉排期与烧制批次系统")
    parser.add_argument("--port", type=int, default=8000, help="监听端口（默认 8000）")
    parser.add_argument("--data", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"),
                        help="数据目录（SQLite 与照片，默认 ./data）")
    args = parser.parse_args()

    os.makedirs(args.data, exist_ok=True)
    db_path = os.path.join(args.data, "pottery.db")
    photos_dir = os.path.join(args.data, "photos")

    service = PotteryService(db_path, photos_dir=photos_dir)
    if seed_if_empty(service):
        print("✔ 已载入样例数据：班级/匿名学生/泥料釉色/窑炉/程序/作品")
        print("  含釉料相冲、装载超高、干燥不足、标签脱落、停电中断、裂损补烧、少件样例")
    else:
        print("✔ 使用已有数据：", db_path)

    scheduler = Scheduler(service, interval=1.0)
    scheduler.start()

    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pottery", "static")
    server = serve(service, static_dir, port=args.port)
    print(f"✔ 窑炉排期系统已启动： http://localhost:{args.port}")
    print("  账号：admin（管理员）/ wang、li（教师）/ s01~s12（学生，匿名）")
    print("  Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止…")
    finally:
        scheduler.stop()
        server.shutdown()
        service.close()


if __name__ == "__main__":
    main()
