"""业务服务层：作品登记、干燥队列、排期、装窑、点火、停电、开窑、清点、补烧。

所有业务规则集中在这里，Web 层与测试共用：
- 作品须干燥合格才可排入素烧；
- 窑炉时段不能重叠；同一作品不能加入两个未结束批次；
- 装窑校验尺寸（层净高）与釉料相容性；点火后批次与程序锁定；
- 完全冷却才能开窑，异常开窑需管理员并留痕；补烧必须引用原作品与失败原因。
"""
from __future__ import annotations

import os
import sqlite3
import threading
from datetime import datetime, timedelta

from . import domain
from .db import connect, init_db

# ---- 作品状态 ----
WORK_DRYING = "drying"              # 自然干燥中
WORK_QUALIFIED = "dry_qualified"    # 干燥合格，可排烧
WORK_SCHEDULED = "scheduled"        # 已装入未点火批次
WORK_FIRING = "firing"              # 烧制/冷却流程中
WORK_COMPLETED = "completed"        # 成品
WORK_DAMAGED = "damaged"            # 裂损
WORK_MISSING = "missing"            # 少件
WORK_REFIRE = "refire_pending"      # 待补烧

# ---- 批次状态 ----
B_SCHEDULED = "scheduled"
B_FIRING = "firing"
B_COOLING = "cooling"
B_COOLED = "cooled"
B_OPENED = "opened"
B_INTERRUPTED = "interrupted"

BATCH_UNFINISHED = (B_SCHEDULED, B_FIRING, B_COOLING, B_COOLED, B_INTERRUPTED)  # 未结束
BATCH_OCCUPYING = (B_FIRING, B_COOLING, B_COOLED, B_INTERRUPTED)                # 实际占用窑炉

ROLE_ADMIN = "admin"
ROLE_TEACHER = "teacher"
ROLE_STUDENT = "student"
STAFF = (ROLE_ADMIN, ROLE_TEACHER)

# ---- 异常留痕类型 ----
INC_LABEL = "label_detached"          # 标签脱落
INC_DRYING = "insufficient_drying"    # 干燥不足
INC_GLAZE = "glaze_conflict"          # 釉料相冲
INC_HEIGHT = "over_height"            # 装载超高
INC_OUTAGE = "power_outage"           # 停电中断
INC_RESTORE = "power_restored"        # 恢复供电
INC_EARLY_OPEN = "early_open"         # 异常开窑
INC_CRACK = "crack"                   # 裂损
INC_MISSING = "missing_piece"         # 少件

INCIDENT_LABELS = {
    INC_LABEL: "标签脱落",
    INC_DRYING: "干燥不足",
    INC_GLAZE: "釉料相冲",
    INC_HEIGHT: "装载超高",
    INC_OUTAGE: "停电中断",
    INC_RESTORE: "恢复供电",
    INC_EARLY_OPEN: "异常开窑",
    INC_CRACK: "裂损",
    INC_MISSING: "作品少件",
}

WORK_STATUS_LABELS = {
    WORK_DRYING: "自然干燥中",
    WORK_QUALIFIED: "干燥合格",
    WORK_SCHEDULED: "已排入批次",
    WORK_FIRING: "烧制流程中",
    WORK_COMPLETED: "成品",
    WORK_DAMAGED: "裂损",
    WORK_MISSING: "少件",
    WORK_REFIRE: "待补烧",
}

BATCH_STATUS_LABELS = {
    B_SCHEDULED: "已排期",
    B_FIRING: "烧制中",
    B_COOLING: "冷却中",
    B_COOLED: "待开窑",
    B_OPENED: "已开窑",
    B_INTERRUPTED: "停电中断",
}


class DomainError(Exception):
    """业务规则错误。"""

    def __init__(self, message: str, code: str = "domain"):
        super().__init__(message)
        self.code = code


class PermissionDenied(DomainError):
    def __init__(self, message: str = "权限不足，无法执行该操作"):
        super().__init__(message, "permission")


class NotFound(DomainError):
    def __init__(self, message: str = "记录不存在"):
        super().__init__(message, "not_found")


def _dt(s: str) -> datetime:
    return domain.parse_dt(s)


def _iso(dt: datetime) -> str:
    return domain.iso(dt)


class PotteryService:
    def __init__(self, db_path: str, photos_dir: str | None = None, clock=datetime.now):
        self.db_path = db_path
        self.conn = connect(db_path)
        init_db(self.conn)
        self.lock = threading.RLock()
        self.clock = clock
        self.photos_dir = photos_dir or os.path.join(os.path.dirname(db_path), "photos")
        os.makedirs(self.photos_dir, exist_ok=True)

    # ---------------------------------------------------------------- 基础
    def now(self) -> datetime:
        return self.clock()

    def close(self):
        self.conn.close()

    def _one(self, sql: str, args=()):
        return self.conn.execute(sql, args).fetchone()

    def _all(self, sql: str, args=()):
        return self.conn.execute(sql, args).fetchall()

    def _get_or_404(self, table: str, row_id: int, label: str):
        row = self._one(f"SELECT * FROM {table} WHERE id = ?", (row_id,))
        if row is None:
            raise NotFound(f"{label}不存在")
        return row

    def _user(self, user_id: int) -> sqlite3.Row:
        return self._get_or_404("users", user_id, "用户")

    def _require(self, user_id: int, roles) -> sqlite3.Row:
        user = self._user(user_id)
        if user["role"] not in roles:
            raise PermissionDenied()
        return user

    def _log(self, inc_type: str, work_id=None, batch_id=None, actor_id=None, detail=""):
        self.conn.execute(
            "INSERT INTO incidents (type, work_id, batch_id, actor_id, detail, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (inc_type, work_id, batch_id, actor_id, detail, _iso(self.now())),
        )

    def _log_rejection(self, inc_type: str, work_id=None, batch_id=None, actor_id=None,
                       detail=""):
        """拒绝路径上的留痕：立即提交，避免随后抛错被事务回滚。"""
        self._log(inc_type, work_id=work_id, batch_id=batch_id, actor_id=actor_id,
                  detail=detail)
        self.conn.commit()

    # ---------------------------------------------------------------- 作品与干燥
    def register_work(self, actor_id, student_id, clay_id, glaze_id,
                      width_cm, depth_cm, height_cm, drying_hours=48.0) -> int:
        """作品登记：完成后即进入自然干燥。"""
        with self.lock, self.conn:
            self._require(actor_id, STAFF)
            self._get_or_404("students", student_id, "学生")
            self._get_or_404("clays", clay_id, "泥料")
            self._get_or_404("glazes", glaze_id, "釉色")
            w, d, h = float(width_cm), float(depth_cm), float(height_cm)
            if min(w, d, h) <= 0:
                raise DomainError("作品尺寸必须为正数")
            if float(drying_hours) <= 0:
                raise DomainError("干燥时长必须为正数")
            next_id = (self._one("SELECT COALESCE(MAX(id), 0) + 1 AS n FROM works"))["n"]
            code = f"W{next_id:03d}"
            cur = self.conn.execute(
                "INSERT INTO works (code, student_id, clay_id, glaze_id, width_cm, depth_cm,"
                " height_cm, status, drying_started_at, drying_required_hours, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (code, student_id, clay_id, glaze_id, w, d, h,
                 WORK_DRYING, _iso(self.now()), float(drying_hours), _iso(self.now())),
            )
            return cur.lastrowid

    def confirm_drying(self, actor_id, work_id: int):
        """教师确认干燥合格；干燥时间不足则拒绝并留痕。"""
        with self.lock, self.conn:
            actor = self._require(actor_id, STAFF)
            work = self._get_or_404("works", work_id, "作品")
            if work["status"] != WORK_DRYING:
                raise DomainError("该作品不在干燥队列中")
            elapsed = (self.now() - _dt(work["drying_started_at"])).total_seconds() / 3600.0
            required = work["drying_required_hours"]
            if elapsed < required:
                detail = f"已干燥 {elapsed:.1f}h / 要求 {required:.0f}h"
                self._log_rejection(INC_DRYING, work_id=work_id, actor_id=actor["id"],
                                    detail=detail)
                raise DomainError(f"干燥时间不足（{detail}），不能确认合格")
            self.conn.execute(
                "UPDATE works SET status = ?, drying_confirmed_at = ?, drying_confirmed_by = ?"
                " WHERE id = ?",
                (WORK_QUALIFIED, _iso(self.now()), actor["id"], work_id),
            )

    def report_label_detached(self, actor_id, work_id: int):
        """作品标签脱落：标记并留痕。"""
        with self.lock, self.conn:
            actor = self._require(actor_id, STAFF)
            work = self._get_or_404("works", work_id, "作品")
            self.conn.execute("UPDATE works SET label_detached = 1 WHERE id = ?", (work_id,))
            self._log(INC_LABEL, work_id=work_id, actor_id=actor["id"],
                      detail=f"作品 {work['code']} 标签脱落，已按代号重新登记")

    def drying_queue(self):
        rows = self._all(
            "SELECT w.*, s.anon_code, c.name AS class_name, g.name AS glaze_name, g.color_hex,"
            " cl.name AS clay_name"
            " FROM works w"
            " JOIN students s ON s.id = w.student_id"
            " JOIN classes c ON c.id = s.class_id"
            " JOIN glazes g ON g.id = w.glaze_id"
            " JOIN clays cl ON cl.id = w.clay_id"
            " WHERE w.status = ? ORDER BY w.drying_started_at",
            (WORK_DRYING,),
        )
        now = self.now()
        out = []
        for r in rows:
            elapsed = (now - _dt(r["drying_started_at"])).total_seconds() / 3600.0
            required = r["drying_required_hours"]
            out.append({
                **dict(r),
                "elapsed_hours": elapsed,
                "remaining_hours": max(0.0, required - elapsed),
                "ready": elapsed >= required,
            })
        return out

    def loadable_works(self):
        """可装窑作品：干燥合格或待补烧，且不在任何未结束批次中。"""
        marks = ",".join("?" for _ in BATCH_UNFINISHED)
        return self._all(
            f"SELECT w.*, s.anon_code, g.name AS glaze_name, g.color_hex, cl.name AS clay_name"
            f" FROM works w"
            f" JOIN students s ON s.id = w.student_id"
            f" JOIN glazes g ON g.id = w.glaze_id"
            f" JOIN clays cl ON cl.id = w.clay_id"
            f" WHERE w.status IN (?, ?)"
            f" AND NOT EXISTS (SELECT 1 FROM batch_items bi JOIN batches b ON b.id = bi.batch_id"
            f"                  WHERE bi.work_id = w.id AND b.status IN ({marks}))"
            f" ORDER BY w.code",
            (WORK_QUALIFIED, WORK_REFIRE, *BATCH_UNFINISHED),
        )

    # ---------------------------------------------------------------- 排期
    def _kiln_busy_ranges(self, kiln_id: int, exclude_batch_id=None):
        """窑炉已被占用的时间段（未开窑批次；已点火的按实际时段）。"""
        rows = self._all(
            "SELECT * FROM batches WHERE kiln_id = ? AND status != ?", (kiln_id, B_OPENED))
        ranges = []
        for b in rows:
            if exclude_batch_id and b["id"] == exclude_batch_id:
                continue
            if b["ignited_at"]:
                ranges.append((_dt(b["ignited_at"]), _dt(b["cooled_at"]), b["name"]))
            else:
                ranges.append((_dt(b["scheduled_start"]), _dt(b["scheduled_end"]), b["name"]))
        return ranges

    def schedule_batch(self, actor_id, kiln_id, program_id, name, kind,
                       start: datetime, end: datetime) -> int:
        """教师排期：同一窑炉时段不能重叠。"""
        with self.lock, self.conn:
            actor = self._require(actor_id, STAFF)
            self._get_or_404("kilns", kiln_id, "窑炉")
            self._get_or_404("programs", program_id, "烧制程序")
            if kind not in ("bisque", "glaze"):
                raise DomainError("批次类型须为素烧或釉烧")
            if not name or not name.strip():
                raise DomainError("请填写批次名称")
            if end <= start:
                raise DomainError("结束时间必须晚于开始时间")
            for b_start, b_end, b_name in self._kiln_busy_ranges(kiln_id):
                if domain.ranges_overlap(start, end, b_start, b_end):
                    raise DomainError(
                        f"与批次「{b_name}」时段冲突（{domain.fmt_dt(domain.iso(b_start))}"
                        f" ~ {domain.fmt_dt(domain.iso(b_end))}），窑炉时段不能重叠")
            cur = self.conn.execute(
                "INSERT INTO batches (name, kiln_id, program_id, kind, status,"
                " scheduled_start, scheduled_end, created_by, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (name.strip(), kiln_id, program_id, kind, B_SCHEDULED,
                 _iso(start), _iso(end), actor["id"], _iso(self.now())),
            )
            return cur.lastrowid

    # ---------------------------------------------------------------- 装窑
    def _glaze_conflict_reason(self, glaze_x: int, glaze_y: int):
        a, b = min(glaze_x, glaze_y), max(glaze_x, glaze_y)
        row = self._one(
            "SELECT gc.reason, ga.name AS na, gb.name AS nb FROM glaze_conflicts gc"
            " JOIN glazes ga ON ga.id = gc.glaze_a JOIN glazes gb ON gb.id = gc.glaze_b"
            " WHERE gc.glaze_a = ? AND gc.glaze_b = ?", (a, b))
        if row:
            reason = row["reason"] or "釉料相冲"
            return f"{row['na']} × {row['nb']}：{reason}"
        return None

    def _check_loadable(self, batch, work, shelf_no: int):
        """装窑约束校验，失败时留痕并抛错。返回 kiln 行。"""
        kiln = self._get_or_404("kilns", batch["kiln_id"], "窑炉")
        if not (1 <= int(shelf_no) <= kiln["shelf_count"]):
            raise DomainError(f"棚板层号须在 1~{kiln['shelf_count']} 之间")
        # 装载超高
        if work["height_cm"] > kiln["shelf_clearance_cm"]:
            detail = (f"作品 {work['code']} 高 {work['height_cm']:.0f}cm，"
                      f"超过 {kiln['name']} 层净高 {kiln['shelf_clearance_cm']:.0f}cm")
            self._log_rejection(INC_HEIGHT, work_id=work["id"], batch_id=batch["id"],
                                detail=detail)
            raise DomainError(f"装载超高：{detail}")
        # 容量
        count = self._one(
            "SELECT COUNT(*) AS n FROM batch_items WHERE batch_id = ? AND shelf_no = ?",
            (batch["id"], shelf_no))["n"]
        if count >= kiln["shelf_slots"]:
            raise DomainError(f"第 {shelf_no} 层已满（{kiln['shelf_slots']} 个工位）")
        # 釉料相容性（同层）
        shelf_glazes = self._all(
            "SELECT w.glaze_id, w.code FROM batch_items bi JOIN works w ON w.id = bi.work_id"
            " WHERE bi.batch_id = ? AND bi.shelf_no = ?", (batch["id"], shelf_no))
        for other in shelf_glazes:
            reason = self._glaze_conflict_reason(work["glaze_id"], other["glaze_id"])
            if reason:
                detail = f"作品 {work['code']} 与同层 {other['code']} 釉料相冲（{reason}）"
                self._log_rejection(INC_GLAZE, work_id=work["id"], batch_id=batch["id"],
                                    detail=detail)
                raise DomainError(f"釉料相冲：{detail}")
        return kiln

    def _next_slot(self, batch_id: int, shelf_no: int, slots: int) -> int:
        used = {r["slot_no"] for r in self._all(
            "SELECT slot_no FROM batch_items WHERE batch_id = ? AND shelf_no = ?",
            (batch_id, shelf_no))}
        for n in range(1, slots + 1):
            if n not in used:
                return n
        raise DomainError("该层已满")

    def add_work_to_batch(self, actor_id, batch_id: int, work_id: int, shelf_no: int):
        """装窑：校验干燥合格、作品唯一、尺寸、釉料相容、容量。"""
        with self.lock, self.conn:
            self._require(actor_id, STAFF)
            batch = self._get_or_404("batches", batch_id, "批次")
            if batch["status"] != B_SCHEDULED:
                raise DomainError("批次已点火锁定，不能再装窑")
            work = self._get_or_404("works", work_id, "作品")
            # 同一作品不能加入两个未结束批次
            marks = ",".join("?" for _ in BATCH_UNFINISHED)
            dup = self._one(
                f"SELECT b.id, b.name FROM batch_items bi JOIN batches b ON b.id = bi.batch_id"
                f" WHERE bi.work_id = ? AND b.status IN ({marks})",
                (work_id, *BATCH_UNFINISHED))
            if dup:
                raise DomainError(f"作品 {work['code']} 已在未结束批次「{dup['name']}」中")
            if work["status"] not in (WORK_QUALIFIED, WORK_REFIRE):
                raise DomainError("作品未通过干燥确认，不能排入烧制")
            kiln = self._check_loadable(batch, work, int(shelf_no))
            slot = self._next_slot(batch_id, int(shelf_no), kiln["shelf_slots"])
            self.conn.execute(
                "INSERT INTO batch_items (batch_id, work_id, shelf_no, slot_no) VALUES (?, ?, ?, ?)",
                (batch_id, work_id, int(shelf_no), slot))
            self.conn.execute("UPDATE works SET status = ? WHERE id = ?", (WORK_SCHEDULED, work_id))
            refire = self._one(
                "SELECT id FROM refires WHERE work_id = ? AND status = 'pending'", (work_id,))
            if refire:
                self.conn.execute(
                    "UPDATE refires SET status = 'scheduled', new_batch_id = ? WHERE id = ?",
                    (batch_id, refire["id"]))

    def auto_assign(self, actor_id, batch_id: int, work_ids: list[int]) -> dict:
        """按尺寸与釉料相容性自动分配棚板（先高后矮、逐层尝试）。"""
        with self.lock, self.conn:
            self._require(actor_id, STAFF)
            batch = self._get_or_404("batches", batch_id, "批次")
            if batch["status"] != B_SCHEDULED:
                raise DomainError("批次已点火锁定，不能再装窑")
            kiln = self._get_or_404("kilns", batch["kiln_id"], "窑炉")
            works = [self._get_or_404("works", wid, "作品") for wid in work_ids]
            works.sort(key=lambda w: w["height_cm"], reverse=True)
            placed, failed = [], []
            for work in works:
                ok = False
                last_err = "无可用棚板"
                for shelf in range(1, kiln["shelf_count"] + 1):
                    try:
                        self.add_work_to_batch(actor_id, batch_id, work["id"], shelf)
                        placed.append({"work_id": work["id"], "code": work["code"], "shelf": shelf})
                        ok = True
                        break
                    except DomainError as e:
                        last_err = str(e)
                        continue
                if not ok:
                    failed.append({"work_id": work["id"], "code": work["code"], "reason": last_err})
            return {"placed": placed, "failed": failed}

    def remove_work_from_batch(self, actor_id, item_id: int):
        with self.lock, self.conn:
            self._require(actor_id, STAFF)
            item = self._get_or_404("batch_items", item_id, "装窑记录")
            batch = self._get_or_404("batches", item["batch_id"], "批次")
            if batch["status"] != B_SCHEDULED:
                raise DomainError("批次已点火锁定，不能取出作品")
            self.conn.execute("DELETE FROM batch_items WHERE id = ?", (item_id,))
            refire = self._one(
                "SELECT id FROM refires WHERE work_id = ? AND status = 'scheduled'"
                " AND new_batch_id = ?", (item["work_id"], batch["id"]))
            if refire:
                self.conn.execute(
                    "UPDATE refires SET status = 'pending', new_batch_id = NULL WHERE id = ?",
                    (refire["id"],))
                self.conn.execute("UPDATE works SET status = ? WHERE id = ?",
                                  (WORK_REFIRE, item["work_id"]))
            else:
                self.conn.execute("UPDATE works SET status = ? WHERE id = ?",
                                  (WORK_QUALIFIED, item["work_id"]))

    def change_program(self, actor_id, batch_id: int, program_id: int):
        """点火前可调整程序；点火后锁定。"""
        with self.lock, self.conn:
            self._require(actor_id, STAFF)
            batch = self._get_or_404("batches", batch_id, "批次")
            if batch["status"] != B_SCHEDULED:
                raise DomainError("批次已点火，程序已锁定")
            program = self._get_or_404("programs", program_id, "烧制程序")
            self.conn.execute(
                "UPDATE batches SET program_id = ?, kind = ? WHERE id = ?",
                (program_id, program["kind"], batch_id))

    # ---------------------------------------------------------------- 点火与停电
    def ignite(self, actor_id, batch_id: int):
        """点火（仅管理员）：锁定批次与程序，计算烧制/冷却时点。"""
        with self.lock, self.conn:
            actor = self._require(actor_id, (ROLE_ADMIN,))
            batch = self._get_or_404("batches", batch_id, "批次")
            if batch["status"] != B_SCHEDULED:
                raise DomainError("只有已排期的批次可以点火")
            n_items = self._one(
                "SELECT COUNT(*) AS n FROM batch_items WHERE batch_id = ?", (batch_id,))["n"]
            if n_items == 0:
                raise DomainError("空窑不能点火，请先装窑")
            kiln = self._get_or_404("kilns", batch["kiln_id"], "窑炉")
            marks = ",".join("?" for _ in BATCH_OCCUPYING)
            busy = self._one(
                f"SELECT id, name FROM batches WHERE kiln_id = ? AND id != ?"
                f" AND status IN ({marks})",
                (batch["kiln_id"], batch_id, *BATCH_OCCUPYING))
            if busy:
                raise DomainError(f"窑炉正被批次「{busy['name']}」占用，不能点火")
            program = self._get_or_404("programs", batch["program_id"], "烧制程序")
            segments = domain.parse_segments(program["segments"])
            now = self.now()
            firing_end = now + timedelta(minutes=domain.program_duration_minutes(segments))
            cooled = firing_end + timedelta(hours=kiln["cooling_hours"])
            # 实际占用时段不得与其他排期重叠
            for b_start, b_end, b_name in self._kiln_busy_ranges(kiln["id"], exclude_batch_id=batch_id):
                if domain.ranges_overlap(now, cooled, b_start, b_end):
                    raise DomainError(f"实际烧制时段与批次「{b_name}」冲突，请先调整排期")
            self.conn.execute(
                "UPDATE batches SET status = ?, ignited_at = ?, ignited_by = ?,"
                " firing_end_at = ?, cooled_at = ? WHERE id = ?",
                (B_FIRING, _iso(now), actor["id"], _iso(firing_end), _iso(cooled), batch_id))
            self.conn.execute(
                "UPDATE works SET status = ? WHERE id IN"
                " (SELECT work_id FROM batch_items WHERE batch_id = ?)",
                (WORK_FIRING, batch_id))

    def report_power_outage(self, actor_id, batch_id: int, detail="市电中断"):
        """停电中断（仅管理员），留痕。"""
        with self.lock, self.conn:
            actor = self._require(actor_id, (ROLE_ADMIN,))
            batch = self._get_or_404("batches", batch_id, "批次")
            if batch["status"] not in (B_FIRING, B_COOLING):
                raise DomainError("只有烧制/冷却中的批次会受停电影响")
            self.conn.execute(
                "UPDATE batches SET status = ?, interrupted_at = ? WHERE id = ?",
                (B_INTERRUPTED, _iso(self.now()), batch_id))
            self._log(INC_OUTAGE, batch_id=batch_id, actor_id=actor["id"], detail=detail)

    def restore_power(self, actor_id, batch_id: int):
        """恢复供电（仅管理员）：烧制与冷却时点按中断时长顺延。"""
        with self.lock, self.conn:
            actor = self._require(actor_id, (ROLE_ADMIN,))
            batch = self._get_or_404("batches", batch_id, "批次")
            if batch["status"] != B_INTERRUPTED:
                raise DomainError("该批次不在停电中断状态")
            now = self.now()
            shift = now - _dt(batch["interrupted_at"])
            firing_end = _dt(batch["firing_end_at"]) + shift
            cooled = _dt(batch["cooled_at"]) + shift
            self.conn.execute(
                "UPDATE batches SET status = ?, firing_end_at = ?, cooled_at = ?,"
                " interrupted_at = NULL WHERE id = ?",
                (B_FIRING, _iso(firing_end), _iso(cooled), batch_id))
            self._log(INC_RESTORE, batch_id=batch_id, actor_id=actor["id"],
                      detail=f"供电恢复，中断 {shift.total_seconds() / 60:.0f} 分钟，时点顺延")

    # ---------------------------------------------------------------- 开窑与清点
    def open_kiln(self, actor_id, batch_id: int):
        """开窑：完全冷却后教师可开；未冷却属异常开窑，需管理员并留痕。"""
        with self.lock, self.conn:
            actor = self._require(actor_id, STAFF)
            batch = self._get_or_404("batches", batch_id, "批次")
            early = False
            if batch["status"] == B_COOLED:
                pass
            elif batch["status"] in (B_FIRING, B_COOLING, B_INTERRUPTED):
                if actor["role"] != ROLE_ADMIN:
                    raise PermissionDenied("窑炉尚未完全冷却，异常开窑需管理员权限")
                early = True
                temp, _phase = self._current_temp(batch)
                self._log(INC_EARLY_OPEN, batch_id=batch_id, actor_id=actor["id"],
                          detail=f"异常开窑：开窑时窑温约 {temp:.0f}°C，未完全冷却")
            elif batch["status"] == B_SCHEDULED:
                raise DomainError("批次尚未点火，不能开窑")
            else:
                raise DomainError("批次已开窑")
            self.conn.execute(
                "UPDATE batches SET status = ?, opened_at = ?, opened_by = ?, early_open = ?"
                " WHERE id = ?",
                (B_OPENED, _iso(self.now()), actor["id"], 1 if early else 0, batch_id))

    def record_inventory(self, actor_id, batch_id: int, results: dict[int, tuple[str, str]]):
        """出窑清点：逐件登记 ok / cracked / missing，裂损与少件留痕。"""
        with self.lock, self.conn:
            actor = self._require(actor_id, STAFF)
            batch = self._get_or_404("batches", batch_id, "批次")
            if batch["status"] != B_OPENED:
                raise DomainError("请先开窑，再做出窑清点")
            items = self._all(
                "SELECT bi.*, w.code FROM batch_items bi JOIN works w ON w.id = bi.work_id"
                " WHERE bi.batch_id = ?", (batch_id,))
            if not items:
                raise DomainError("该批次没有装窑作品")
            # 先整体校验，再统一落库，避免部分写入
            pending = []
            for item in items:
                if item["result"] is not None:
                    continue
                if item["id"] not in results:
                    raise DomainError(f"作品 {item['code']} 尚未登记出窑结果")
                result, note = results[item["id"]]
                if result not in ("ok", "cracked", "missing"):
                    raise DomainError("出窑结果须为 完好/裂损/少件")
                pending.append((item, result, note or ""))
            for item, result, note in pending:
                self.conn.execute(
                    "UPDATE batch_items SET result = ?, result_note = ? WHERE id = ?",
                    (result, note, item["id"]))
                if result == "ok":
                    new_status = WORK_COMPLETED
                elif result == "cracked":
                    new_status = WORK_DAMAGED
                    self._log(INC_CRACK, work_id=item["work_id"], batch_id=batch_id,
                              actor_id=actor["id"],
                              detail=f"出窑清点：作品 {item['code']} 裂损。{note or ''}".strip())
                else:
                    new_status = WORK_MISSING
                    self._log(INC_MISSING, work_id=item["work_id"], batch_id=batch_id,
                              actor_id=actor["id"],
                              detail=f"出窑清点：作品 {item['code']} 少件。{note or ''}".strip())
                self.conn.execute("UPDATE works SET status = ? WHERE id = ?",
                                  (new_status, item["work_id"]))
                refire = self._one(
                    "SELECT id FROM refires WHERE work_id = ? AND status = 'scheduled'"
                    " AND new_batch_id = ?", (item["work_id"], batch_id))
                if refire:
                    if result == "ok":
                        self.conn.execute("UPDATE refires SET status = 'done' WHERE id = ?",
                                          (refire["id"],))
                    else:
                        self.conn.execute(
                            "UPDATE refires SET status = 'pending', new_batch_id = NULL"
                            " WHERE id = ?", (refire["id"],))

    # ---------------------------------------------------------------- 补烧
    def create_refire(self, actor_id, work_id: int, reason: str) -> int:
        """补烧：必须引用原作品与失败原因。"""
        with self.lock, self.conn:
            actor = self._require(actor_id, STAFF)
            work = self._get_or_404("works", work_id, "作品")
            if work["status"] != WORK_DAMAGED:
                raise DomainError("只有裂损作品可以安排补烧")
            if not reason or not reason.strip():
                raise DomainError("补烧必须填写失败原因")
            existing = self._one(
                "SELECT id FROM refires WHERE work_id = ? AND status IN ('pending', 'scheduled')",
                (work_id,))
            if existing:
                raise DomainError("该作品已有进行中的补烧记录")
            source = self._one(
                "SELECT batch_id FROM batch_items WHERE work_id = ? AND result = 'cracked'"
                " ORDER BY id DESC", (work_id,))
            if not source:
                raise DomainError("找不到原烧制批次，无法补烧")
            cur = self.conn.execute(
                "INSERT INTO refires (work_id, source_batch_id, reason, status, created_by, created_at)"
                " VALUES (?, ?, ?, 'pending', ?, ?)",
                (work_id, source["batch_id"], reason.strip(), actor["id"], _iso(self.now())))
            self.conn.execute("UPDATE works SET status = ? WHERE id = ?", (WORK_REFIRE, work_id))
            return cur.lastrowid

    # ---------------------------------------------------------------- 照片
    def attach_photo(self, actor_id, kind: str, filename: str,
                     work_id=None, batch_id=None) -> int:
        with self.lock, self.conn:
            actor = self._require(actor_id, STAFF)
            if kind not in ("loading", "finished"):
                raise DomainError("照片类型须为装窑或成品")
            if work_id is None and batch_id is None:
                raise DomainError("照片须关联作品或批次")
            cur = self.conn.execute(
                "INSERT INTO photos (kind, work_id, batch_id, filename, uploaded_by, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (kind, work_id, batch_id, filename, actor["id"], _iso(self.now())))
            return cur.lastrowid

    # ---------------------------------------------------------------- 查询
    def _current_temp(self, batch) -> tuple[float, str]:
        """由批次与程序推算当前窑温（供留痕与展示）。"""
        from .kiln_adapter import SimulatedKilnAdapter
        return SimulatedKilnAdapter(self).temp_for_batch(batch)

    def batch_detail(self, batch_id: int) -> dict:
        batch = self._get_or_404("batches", batch_id, "批次")
        kiln = self._get_or_404("kilns", batch["kiln_id"], "窑炉")
        program = self._get_or_404("programs", batch["program_id"], "烧制程序")
        items = self._all(
            "SELECT bi.id AS item_id, bi.shelf_no, bi.slot_no, bi.result, bi.result_note,"
            " w.id AS work_id, w.code, w.width_cm, w.depth_cm, w.height_cm,"
            " w.status AS work_status, w.label_detached,"
            " g.name AS glaze_name, g.color_hex, s.anon_code"
            " FROM batch_items bi"
            " JOIN works w ON w.id = bi.work_id"
            " JOIN glazes g ON g.id = w.glaze_id"
            " JOIN students s ON s.id = w.student_id"
            " WHERE bi.batch_id = ? ORDER BY bi.shelf_no, bi.slot_no", (batch_id,))
        photos = self._all(
            "SELECT * FROM photos WHERE batch_id = ? ORDER BY id", (batch_id,))
        incidents = self._all(
            "SELECT i.*, u.display_name AS actor_name, w.code AS work_code"
            " FROM incidents i"
            " LEFT JOIN users u ON u.id = i.actor_id"
            " LEFT JOIN works w ON w.id = i.work_id"
            " WHERE i.batch_id = ? ORDER BY i.id DESC", (batch_id,))
        creator = self._one("SELECT display_name FROM users WHERE id = ?", (batch["created_by"],))
        igniter = (self._one("SELECT display_name FROM users WHERE id = ?", (batch["ignited_by"],))
                   if batch["ignited_by"] else None)
        return {
            "batch": dict(batch), "kiln": dict(kiln), "program": dict(program),
            "segments": domain.parse_segments(program["segments"]),
            "items": [dict(i) for i in items],
            "photos": [dict(p) for p in photos],
            "incidents": [dict(i) for i in incidents],
            "creator": creator["display_name"] if creator else "—",
            "igniter": igniter["display_name"] if igniter else None,
        }

    def kiln_cards(self):
        """仪表盘：每座窑的当前状态。"""
        cards = []
        for kiln in self._all("SELECT * FROM kilns ORDER BY id"):
            marks = ",".join("?" for _ in BATCH_OCCUPYING)
            active = self._one(
                f"SELECT * FROM batches WHERE kiln_id = ? AND status IN ({marks})"
                f" ORDER BY ignited_at DESC LIMIT 1",
                (kiln["id"], *BATCH_OCCUPYING))
            upcoming = self._one(
                "SELECT * FROM batches WHERE kiln_id = ? AND status = ?"
                " ORDER BY scheduled_start LIMIT 1",
                (kiln["id"], B_SCHEDULED))
            cards.append({"kiln": dict(kiln),
                          "active": dict(active) if active else None,
                          "upcoming": dict(upcoming) if upcoming else None})
        return cards

    def calendar_batches(self, week_start: datetime, week_end: datetime):
        rows = self._all(
            "SELECT b.*, k.name AS kiln_name, p.name AS program_name"
            " FROM batches b JOIN kilns k ON k.id = b.kiln_id"
            " JOIN programs p ON p.id = b.program_id"
            " WHERE b.status != ? ORDER BY b.scheduled_start", (B_OPENED,))
        out = []
        for b in rows:
            if b["ignited_at"]:
                start, end = _dt(b["ignited_at"]), _dt(b["cooled_at"])
            else:
                start, end = _dt(b["scheduled_start"]), _dt(b["scheduled_end"])
            if domain.ranges_overlap(start, end, week_start, week_end):
                out.append({**dict(b), "range_start": start, "range_end": end})
        return out

    def list_batches(self, limit=30):
        return self._all(
            "SELECT b.*, k.name AS kiln_name, p.name AS program_name,"
            " (SELECT COUNT(*) FROM batch_items bi WHERE bi.batch_id = b.id) AS item_count"
            " FROM batches b JOIN kilns k ON k.id = b.kiln_id"
            " JOIN programs p ON p.id = b.program_id"
            " ORDER BY b.id DESC LIMIT ?", (limit,))

    def list_works(self):
        return self._all(
            "SELECT w.*, s.anon_code, c.name AS class_name, g.name AS glaze_name, g.color_hex,"
            " cl.name AS clay_name"
            " FROM works w"
            " JOIN students s ON s.id = w.student_id"
            " JOIN classes c ON c.id = s.class_id"
            " JOIN glazes g ON g.id = w.glaze_id"
            " JOIN clays cl ON cl.id = w.clay_id"
            " ORDER BY w.id DESC")

    def work_chain(self, work_id: int) -> dict:
        work = self._get_or_404("works", work_id, "作品")
        student = self._one(
            "SELECT s.anon_code, c.name AS class_name FROM students s"
            " JOIN classes c ON c.id = s.class_id WHERE s.id = ?", (work["student_id"],))
        glaze = self._one("SELECT * FROM glazes WHERE id = ?", (work["glaze_id"],))
        clay = self._one("SELECT * FROM clays WHERE id = ?", (work["clay_id"],))
        items = self._all(
            "SELECT bi.*, b.name AS batch_name, b.status AS batch_status, b.kind AS batch_kind,"
            " k.name AS kiln_name"
            " FROM batch_items bi"
            " JOIN batches b ON b.id = bi.batch_id"
            " JOIN kilns k ON k.id = b.kiln_id"
            " WHERE bi.work_id = ? ORDER BY bi.id", (work_id,))
        incidents = self._all(
            "SELECT i.*, u.display_name AS actor_name, b.name AS batch_name"
            " FROM incidents i"
            " LEFT JOIN users u ON u.id = i.actor_id"
            " LEFT JOIN batches b ON b.id = i.batch_id"
            " WHERE i.work_id = ? ORDER BY i.id DESC", (work_id,))
        photos = self._all("SELECT * FROM photos WHERE work_id = ? ORDER BY id", (work_id,))
        refires = self._all(
            "SELECT r.*, b.name AS source_batch_name, nb.name AS new_batch_name"
            " FROM refires r"
            " JOIN batches b ON b.id = r.source_batch_id"
            " LEFT JOIN batches nb ON nb.id = r.new_batch_id"
            " WHERE r.work_id = ? ORDER BY r.id DESC", (work_id,))
        return {"work": dict(work), "student": dict(student) if student else None,
                "glaze": dict(glaze) if glaze else None, "clay": dict(clay) if clay else None,
                "items": [dict(i) for i in items], "incidents": [dict(i) for i in incidents],
                "photos": [dict(p) for p in photos], "refires": [dict(r) for r in refires]}

    def student_view(self, user_id: int) -> dict:
        user = self._user(user_id)
        student = self._one("SELECT * FROM students WHERE user_id = ?", (user_id,))
        if student is None:
            raise NotFound("该账号未关联学生档案")
        works = self._all(
            "SELECT w.*, g.name AS glaze_name, g.color_hex, cl.name AS clay_name"
            " FROM works w"
            " JOIN glazes g ON g.id = w.glaze_id"
            " JOIN clays cl ON cl.id = w.clay_id"
            " WHERE w.student_id = ? ORDER BY w.id DESC", (student["id"],))
        out = []
        for w in works:
            photos = self._all(
                "SELECT * FROM photos WHERE work_id = ? AND kind = 'finished' ORDER BY id",
                (w["id"],))
            out.append({**dict(w), "photos": [dict(p) for p in photos]})
        clazz = self._one("SELECT name FROM classes WHERE id = ?", (student["class_id"],))
        return {"student": dict(student), "class_name": clazz["name"] if clazz else "",
                "works": out}

    def list_incidents(self, limit=100):
        return self._all(
            "SELECT i.*, u.display_name AS actor_name, w.code AS work_code, b.name AS batch_name"
            " FROM incidents i"
            " LEFT JOIN users u ON u.id = i.actor_id"
            " LEFT JOIN works w ON w.id = i.work_id"
            " LEFT JOIN batches b ON b.id = i.batch_id"
            " ORDER BY i.id DESC LIMIT ?", (limit,))

    def list_refires(self):
        return self._all(
            "SELECT r.*, w.code AS work_code, b.name AS source_batch_name,"
            " nb.name AS new_batch_name, u.display_name AS creator_name"
            " FROM refires r"
            " JOIN works w ON w.id = r.work_id"
            " JOIN batches b ON b.id = r.source_batch_id"
            " LEFT JOIN batches nb ON nb.id = r.new_batch_id"
            " JOIN users u ON u.id = r.created_by"
            " ORDER BY r.id DESC")

    def recent_incidents(self, limit=6):
        return self.list_incidents(limit)

    def counts(self):
        return {
            "drying": self._one("SELECT COUNT(*) AS n FROM works WHERE status = ?",
                                (WORK_DRYING,))["n"],
            "qualified": self._one("SELECT COUNT(*) AS n FROM works WHERE status = ?",
                                   (WORK_QUALIFIED,))["n"],
            "active_batches": self._one(
                "SELECT COUNT(*) AS n FROM batches WHERE status IN (?, ?, ?)",
                (B_FIRING, B_COOLING, B_INTERRUPTED))["n"],
            "incidents": self._one("SELECT COUNT(*) AS n FROM incidents")["n"],
            "refire_pending": self._one(
                "SELECT COUNT(*) AS n FROM refires WHERE status = 'pending'")["n"],
        }

    # ---------------------------------------------------------------- 进程内调度
    def tick(self):
        """进程内任务：推进 烧制中→冷却中→待开窑（依据点火时计算的时点）。"""
        with self.lock, self.conn:
            now = _iso(self.now())
            self.conn.execute(
                "UPDATE batches SET status = ? WHERE status = ? AND firing_end_at IS NOT NULL"
                " AND firing_end_at <= ?", (B_COOLING, B_FIRING, now))
            self.conn.execute(
                "UPDATE batches SET status = ? WHERE status = ? AND cooled_at IS NOT NULL"
                " AND cooled_at <= ?", (B_COOLED, B_COOLING, now))

    # ---------------------------------------------------------------- 字典数据
    def options(self) -> dict:
        return {
            "students": [dict(r) for r in self._all(
                "SELECT s.*, c.name AS class_name FROM students s"
                " JOIN classes c ON c.id = s.class_id ORDER BY s.anon_code")],
            "clays": [dict(r) for r in self._all("SELECT * FROM clays ORDER BY id")],
            "glazes": [dict(r) for r in self._all("SELECT * FROM glazes ORDER BY id")],
            "kilns": [dict(r) for r in self._all("SELECT * FROM kilns ORDER BY id")],
            "programs": [dict(r) for r in self._all("SELECT * FROM programs ORDER BY id")],
            "users": [dict(r) for r in self._all("SELECT * FROM users ORDER BY id")],
        }
