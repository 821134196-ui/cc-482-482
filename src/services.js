'use strict';

const { HttpError, addHours, hoursBetween, requireNumber, requireString, requireIso } = require('./util');
const { computeCurve, readTemperature } = require('./kilnSim');

const ANOMALY_TYPES = new Set([
  'label_lost', 'dry_insufficient', 'glaze_conflict', 'over_height',
  'power_outage', 'early_open', 'cracked', 'missing',
]);

const PACKING_FACTOR = 0.75; // 圆形棚板可用面积系数

class KilnService {
  /**
   * @param {object} opts { db, clock, photoDir }
   * db 与 clock 注入以便测试；photoDir 为本地照片目录。
   */
  constructor({ db, clock, photoDir }) {
    this.db = db;
    this.clock = clock;
    this.photoDir = photoDir;
  }

  now() {
    return this.clock.now();
  }

  // ---------- 基础读取 ----------

  getWork(id) {
    const w = this.db.prepare('SELECT * FROM works WHERE id=?').get(id);
    if (!w) throw new HttpError(404, 'WORK_NOT_FOUND', `作品 ${id} 不存在`);
    return w;
  }

  getBatch(id) {
    const b = this.db.prepare('SELECT * FROM batches WHERE id=?').get(id);
    if (!b) throw new HttpError(404, 'BATCH_NOT_FOUND', `批次 ${id} 不存在`);
    return b;
  }

  getKiln(id) {
    const k = this.db.prepare('SELECT * FROM kilns WHERE id=?').get(id);
    if (!k) throw new HttpError(404, 'KILN_NOT_FOUND', `窑炉 ${id} 不存在`);
    return k;
  }

  getProgram(id) {
    const p = this.db.prepare('SELECT * FROM programs WHERE id=?').get(id);
    if (!p) throw new HttpError(404, 'PROGRAM_NOT_FOUND', `烧制程序 ${id} 不存在`);
    return p;
  }

  /** 统一留痕：异常与生命周期事件都写入 events */
  recordEvent(entityType, entityId, type, detail, actor) {
    this.db.prepare(
      'INSERT INTO events (entity_type, entity_id, type, detail, actor, created_at) VALUES (?,?,?,?,?,?)'
    ).run(entityType, entityId, type, detail == null ? null : String(detail), actor || null, this.now());
  }

  // ---------- 作品登记与干燥 ----------

  /** 作品登记：完成后即进入自然干燥，干燥达标时点由进程内逻辑计算 */
  registerWork(actor, { studentCode, clayId, glazeId, widthMm, depthMm, heightMm }) {
    const student = this.db.prepare('SELECT * FROM students WHERE code=?').get(requireString(studentCode, 'studentCode', { maxLen: 40 }));
    if (!student) throw new HttpError(404, 'STUDENT_NOT_FOUND', `学生代号 ${studentCode} 不存在`);
    const clay = this.db.prepare('SELECT * FROM clays WHERE id=?').get(clayId);
    if (!clay) throw new HttpError(404, 'CLAY_NOT_FOUND', '泥料不存在');
    if (glazeId != null) {
      const g = this.db.prepare('SELECT id FROM glazes WHERE id=?').get(glazeId);
      if (!g) throw new HttpError(404, 'GLAZE_NOT_FOUND', '釉色不存在');
    }
    const w = requireNumber(widthMm, 'widthMm', { min: 10, max: 800 });
    const d = requireNumber(depthMm, 'depthMm', { min: 10, max: 800 });
    const h = requireNumber(heightMm, 'heightMm', { min: 10, max: 800 });

    // 干燥时长 = 泥料基础时长 + 尺寸附加（最大边每 50mm 加 2 小时）
    const required = clay.dry_hours_base + Math.ceil(Math.max(w, d, h) / 50) * 2;
    const now = this.now();
    const seq = Number(this.db.prepare('SELECT COALESCE(MAX(id),0)+1 AS n FROM works').get().n);
    const code = `W-${String(seq).padStart(4, '0')}`;
    const info = this.db.prepare(
      `INSERT INTO works (code, student_id, clay_id, glaze_id, width_mm, depth_mm, height_mm,
        status, dry_required_hours, dry_started_at, dry_due_at, created_at)
       VALUES (?,?,?,?,?,?,?, 'drying', ?,?,?,?)`
    ).run(code, student.id, clay.id, glazeId ?? null, w, d, h, required, now, addHours(now, required), now);
    const id = Number(info.lastInsertRowid);
    this.recordEvent('work', id, 'work_registered',
      `登记 ${code}，${w}×${d}×${h}mm，需自然干燥 ${required} 小时`, actor.username);
    return this.workDetail(id);
  }

  /** 教师确认干燥合格；未达标则留痕 dry_insufficient 并拒绝 */
  confirmDry(actor, workId) {
    const work = this.getWork(workId);
    if (work.status !== 'drying') {
      throw new HttpError(409, 'BAD_STATE', `作品 ${work.code} 当前状态 ${work.status}，不在干燥中`);
    }
    if (this.now() < work.dry_due_at) {
      const remain = Math.ceil(hoursBetween(this.now(), work.dry_due_at));
      this.recordEvent('work', work.id, 'dry_insufficient',
        `干燥不足：还需约 ${remain} 小时（要求 ${work.dry_required_hours}h），${actor.username} 的确认被拒绝`, actor.username);
      throw new HttpError(409, 'DRY_INSUFFICIENT', `干燥不足，还需约 ${remain} 小时，已留痕`);
    }
    this.db.prepare(
      "UPDATE works SET status='dry_qualified', dry_confirmed_at=?, dry_confirmed_by=? WHERE id=?"
    ).run(this.now(), actor.username, work.id);
    this.recordEvent('work', work.id, 'dry_confirmed', `干燥合格，可排入素烧`, actor.username);
    return this.workDetail(work.id);
  }

  /** 作品标签脱落留痕 */
  reportLabelLost(actor, workId, note) {
    const work = this.getWork(workId);
    this.recordEvent('work', work.id, 'label_lost',
      `标签脱落：${note || '需补贴标签'}（作品 ${work.code}）`, actor.username);
    return this.workDetail(work.id);
  }

  // ---------- 批次排期 ----------

  /** 排期：同一窑炉时段不得重叠 */
  createBatch(actor, { name, kilnId, programId, kind, start, end }) {
    const kiln = this.getKiln(kilnId);
    const program = this.getProgram(programId);
    if (!['bisque', 'glaze'].includes(kind)) throw new HttpError(400, 'BAD_KIND', '批次类型须为 bisque 或 glaze');
    if (program.kind !== kind) throw new HttpError(409, 'PROGRAM_KIND_MISMATCH', `程序「${program.name}」是 ${program.kind} 程序，不能用于 ${kind} 批次`);
    const startIso = requireIso(start, 'start');
    const endIso = requireIso(end, 'end');
    if (endIso <= startIso) throw new HttpError(400, 'BAD_RANGE', '结束时间必须晚于开始时间');

    // 已取消/已关闭的批次不再占用窑炉时段
    const clash = this.db.prepare(
      `SELECT id, name, scheduled_start, scheduled_end FROM batches
       WHERE kiln_id=? AND status NOT IN ('cancelled','closed')
         AND scheduled_start < ? AND scheduled_end > ?`
    ).all(kiln.id, endIso, startIso);
    if (clash.length > 0) {
      const c = clash[0];
      throw new HttpError(409, 'SCHEDULE_OVERLAP',
        `窑炉「${kiln.name}」时段与批次「${c.name}」(${c.scheduled_start} ~ ${c.scheduled_end}) 重叠`);
    }

    const info = this.db.prepare(
      `INSERT INTO batches (name, kiln_id, program_id, kind, scheduled_start, scheduled_end, created_by, created_at)
       VALUES (?,?,?,?,?,?,?,?)`
    ).run(requireString(name, 'name', { maxLen: 60 }), kiln.id, program.id, kind, startIso, endIso, actor.username, this.now());
    const id = Number(info.lastInsertRowid);
    this.recordEvent('batch', id, 'batch_created', `排期 ${startIso} ~ ${endIso}（${kiln.name}）`, actor.username);
    return this.batchDetail(id);
  }

  /** 批次加入作品：校验干燥/阶段资格 + 作品唯一性（不能同时处于两个未结束批次） */
  addWorkToBatch(actor, batchId, workId) {
    const batch = this.getBatch(batchId);
    if (!['scheduled', 'loaded'].includes(batch.status)) {
      throw new HttpError(409, 'BATCH_LOCKED', `批次「${batch.name}」已点火或结束，作品与程序已锁定`);
    }
    const work = this.getWork(workId);
    // 先查唯一性：同一作品不能同时处于两个未结束批次
    const busy = this.db.prepare(
      `SELECT b.id, b.name FROM batch_items bi JOIN batches b ON b.id = bi.batch_id
       WHERE bi.work_id=? AND b.status NOT IN ('closed','cancelled')`
    ).all(work.id);
    if (busy.length > 0) {
      throw new HttpError(409, 'WORK_BUSY', `作品 ${work.code} 已在未结束批次「${busy[0].name}」中，不能重复入窑`);
    }
    this.assertEligible(batch, work);

    this.db.prepare('INSERT INTO batch_items (batch_id, work_id) VALUES (?,?)').run(batch.id, work.id);
    this.db.prepare("UPDATE works SET status='scheduled' WHERE id=?").run(work.id);

    const refire = this.db.prepare("SELECT * FROM refires WHERE work_id=? AND status='pending'").get(work.id);
    if (refire) {
      this.db.prepare("UPDATE refires SET new_batch_id=?, status='scheduled' WHERE id=?").run(batch.id, refire.id);
    }
    this.recordEvent('batch', batch.id, 'work_scheduled', `作品 ${work.code} 加入批次`, actor.username);
    this.recordEvent('work', work.id, 'work_scheduled', `排入批次「${batch.name}」`, actor.username);
    return this.batchDetail(batch.id);
  }

  assertEligible(batch, work) {
    const ok = batch.kind === 'bisque'
      ? ((work.status === 'dry_qualified' && work.stage === 'bisque') ||
         (work.status === 'refire_pending' && work.stage === 'bisque'))
      : ((work.status === 'awaiting_glaze' && work.stage === 'glaze' && work.glaze_id != null) ||
         (work.status === 'refire_pending' && work.stage === 'glaze'));
    if (!ok) {
      const need = batch.kind === 'bisque' ? '干燥合格（素烧阶段）' : '素烧完成且已选釉（釉烧阶段）';
      throw new HttpError(409, 'WORK_NOT_ELIGIBLE', `作品 ${work.code} 状态 ${work.status}/${work.stage}，不满足${need}`);
    }
  }

  removeWorkFromBatch(actor, batchId, workId) {
    const batch = this.getBatch(batchId);
    if (!['scheduled', 'loaded'].includes(batch.status)) {
      throw new HttpError(409, 'BATCH_LOCKED', '批次已锁定，不能移除作品');
    }
    const item = this.db.prepare('SELECT * FROM batch_items WHERE batch_id=? AND work_id=?').get(batchId, workId);
    if (!item) throw new HttpError(404, 'ITEM_NOT_FOUND', '该作品不在此批次中');
    this.db.prepare('DELETE FROM batch_items WHERE id=?').run(item.id);
    this.restoreWorkStatus(workId, batch.id);
    if (batch.status === 'loaded') {
      this.db.prepare("UPDATE batches SET status='scheduled' WHERE id=?").run(batchId);
    }
    this.recordEvent('batch', batchId, 'work_removed', `作品 ${this.getWork(workId).code} 移出批次`, actor.username);
    return this.batchDetail(batchId);
  }

  /** 取消排期：释放作品 */
  cancelBatch(actor, batchId) {
    const batch = this.getBatch(batchId);
    if (!['scheduled', 'loaded'].includes(batch.status)) {
      throw new HttpError(409, 'BAD_STATE', '仅未点火的批次可以取消');
    }
    const items = this.db.prepare('SELECT work_id FROM batch_items WHERE batch_id=?').all(batchId);
    this.db.prepare('DELETE FROM batch_items WHERE batch_id=?').run(batchId);
    this.db.prepare("UPDATE batches SET status='cancelled' WHERE id=?").run(batchId);
    for (const it of items) this.restoreWorkStatus(it.work_id, batchId);
    this.recordEvent('batch', batchId, 'batch_cancelled', `批次取消，释放 ${items.length} 件作品`, actor.username);
    return this.batchDetail(batchId);
  }

  restoreWorkStatus(workId, batchId) {
    const work = this.getWork(workId);
    const refire = this.db.prepare('SELECT * FROM refires WHERE work_id=? AND new_batch_id=?').get(workId, batchId);
    if (refire) {
      this.db.prepare("UPDATE refires SET status='pending', new_batch_id=NULL WHERE id=?").run(refire.id);
      this.db.prepare("UPDATE works SET status='refire_pending' WHERE id=?").run(workId);
    } else {
      const back = work.stage === 'bisque' ? 'dry_qualified' : 'awaiting_glaze';
      this.db.prepare('UPDATE works SET status=? WHERE id=?').run(back, workId);
    }
  }

  // ---------- 装窑（棚板分配） ----------

  /** 装载校验：超高 / 釉料相冲 / 容量与面积，违规留痕并拒绝 */
  assignPosition(actor, batchId, workId, shelfNo, angleDeg, radiusMm) {
    const batch = this.getBatch(batchId);
    if (!['scheduled', 'loaded'].includes(batch.status)) {
      throw new HttpError(409, 'BATCH_LOCKED', '批次已点火锁定，不能调整棚板');
    }
    const kiln = this.getKiln(batch.kiln_id);
    const work = this.getWork(workId);
    const item = this.db.prepare('SELECT * FROM batch_items WHERE batch_id=? AND work_id=?').get(batchId, workId);
    if (!item) throw new HttpError(404, 'ITEM_NOT_FOUND', '该作品不在此批次中');
    shelfNo = requireNumber(shelfNo, 'shelfNo', { min: 1, max: kiln.shelf_count });

    if (work.height_mm > kiln.shelf_gap_mm) {
      this.recordEvent('batch', batchId, 'over_height',
        `装载超高：作品 ${work.code} 高 ${work.height_mm}mm 超过层间净高 ${kiln.shelf_gap_mm}mm（第 ${shelfNo} 层）`, actor.username);
      throw new HttpError(409, 'OVER_HEIGHT', `作品 ${work.code} 高 ${work.height_mm}mm 超过层间净高 ${kiln.shelf_gap_mm}mm，已留痕`);
    }

    if (batch.kind === 'glaze' && work.glaze_id != null) {
      const shelfMates = this.db.prepare(
        `SELECT w.id, w.code, w.glaze_id FROM batch_items bi JOIN works w ON w.id = bi.work_id
         WHERE bi.batch_id=? AND bi.shelf_no=? AND w.id != ? AND w.glaze_id IS NOT NULL`
      ).all(batchId, shelfNo, work.id);
      for (const mate of shelfMates) {
        const conflict = this.findGlazeConflict(work.glaze_id, mate.glaze_id);
        if (conflict) {
          this.recordEvent('batch', batchId, 'glaze_conflict',
            `釉料相冲：${work.code}（${this.glazeName(work.glaze_id)}）与 ${mate.code}（${this.glazeName(mate.glaze_id)}）不能同层（第 ${shelfNo} 层）：${conflict.reason || ''}`, actor.username);
          throw new HttpError(409, 'GLAZE_CONFLICT',
            `釉料相冲：${work.code} 与 ${mate.code} 不能同层放置，已留痕`);
        }
      }
    }

    const onShelf = this.db.prepare(
      `SELECT w.width_mm, w.depth_mm FROM batch_items bi JOIN works w ON w.id=bi.work_id
       WHERE bi.batch_id=? AND bi.shelf_no=? AND w.id != ?`
    ).all(batchId, shelfNo, work.id);
    if (onShelf.length >= kiln.shelf_slot_capacity) {
      throw new HttpError(409, 'SHELF_FULL', `第 ${shelfNo} 层已满（${kiln.shelf_slot_capacity} 件）`);
    }
    const usable = Math.PI * kiln.shelf_radius_mm ** 2 * PACKING_FACTOR;
    const used = onShelf.reduce((s, r) => s + r.width_mm * r.depth_mm, 0);
    if (used + work.width_mm * work.depth_mm > usable) {
      throw new HttpError(409, 'SHELF_AREA', `第 ${shelfNo} 层面积不足，无法放下 ${work.code}`);
    }

    // 未指定角度/半径时，自动取该层下一个空槽位（俯视示意用）
    if (angleDeg == null || radiusMm == null) {
      const slots = ringSlots(kiln.shelf_radius_mm);
      const slot = slots[Math.min(onShelf.length, slots.length - 1)];
      angleDeg = slot.angle;
      radiusMm = slot.radius;
    }

    this.db.prepare(
      'UPDATE batch_items SET shelf_no=?, slot_angle_deg=?, slot_radius_mm=? WHERE id=?'
    ).run(shelfNo, angleDeg, radiusMm, item.id);
    this.markLoadedIfComplete(batchId);
    return this.batchLayout(batchId);
  }

  /** 自动排布：按尺寸降序贪心分配到各层，冲突釉色自动分层 */
  autoAssign(actor, batchId) {
    const batch = this.getBatch(batchId);
    if (!['scheduled', 'loaded'].includes(batch.status)) {
      throw new HttpError(409, 'BATCH_LOCKED', '批次已点火锁定');
    }
    const kiln = this.getKiln(batch.kiln_id);
    const items = this.db.prepare(
      `SELECT bi.work_id, w.code, w.width_mm, w.depth_mm, w.height_mm, w.glaze_id
       FROM batch_items bi JOIN works w ON w.id=bi.work_id
       WHERE bi.batch_id=? ORDER BY w.width_mm*w.depth_mm DESC`
    ).all(batchId);
    if (items.length === 0) throw new HttpError(409, 'EMPTY_BATCH', '批次内没有作品');

    for (const it of items) {
      if (it.height_mm > kiln.shelf_gap_mm) {
        this.recordEvent('batch', batchId, 'over_height',
          `装载超高：作品 ${it.code} 高 ${it.height_mm}mm 超过层间净高 ${kiln.shelf_gap_mm}mm，自动排布中止`, actor.username);
        throw new HttpError(409, 'OVER_HEIGHT', `作品 ${it.code} 超高，无法自动排布，已留痕`);
      }
    }

    const shelves = Array.from({ length: kiln.shelf_count }, (_, i) => ({
      no: i + 1, glazes: [], area: 0, count: 0, slots: ringSlots(kiln.shelf_radius_mm), next: 0,
    }));
    const usable = Math.PI * kiln.shelf_radius_mm ** 2 * PACKING_FACTOR;
    const placement = new Map();

    for (const it of items) {
      let placed = false;
      for (const shelf of shelves) {
        if (shelf.count >= kiln.shelf_slot_capacity) continue;
        if (shelf.next >= shelf.slots.length) continue;
        if (shelf.area + it.width_mm * it.depth_mm > usable) continue;
        if (batch.kind === 'glaze' && it.glaze_id != null &&
            shelf.glazes.some((g) => this.findGlazeConflict(it.glaze_id, g))) continue;
        const slot = shelf.slots[shelf.next++];
        shelf.count += 1;
        shelf.area += it.width_mm * it.depth_mm;
        if (it.glaze_id != null) shelf.glazes.push(it.glaze_id);
        placement.set(it.work_id, { shelfNo: shelf.no, angle: slot.angle, radius: slot.radius });
        placed = true;
        break;
      }
      if (!placed) {
        throw new HttpError(409, 'AUTO_ASSIGN_FAILED',
          `作品 ${it.code} 无法排入任何棚板（容量/面积/釉料相容性限制），请调整批次或分批`);
      }
    }

    const upd = this.db.prepare(
      'UPDATE batch_items SET shelf_no=?, slot_angle_deg=?, slot_radius_mm=? WHERE batch_id=? AND work_id=?'
    );
    for (const [workId, p] of placement) upd.run(p.shelfNo, p.angle, p.radius, batchId, workId);
    this.markLoadedIfComplete(batchId);
    this.recordEvent('batch', batchId, 'loaded', `自动排布完成，共 ${items.length} 件`, actor.username);
    return this.batchLayout(batchId);
  }

  markLoadedIfComplete(batchId) {
    const pending = this.db.prepare(
      'SELECT COUNT(*) AS n FROM batch_items WHERE batch_id=? AND shelf_no IS NULL'
    ).get(batchId).n;
    const total = this.db.prepare('SELECT COUNT(*) AS n FROM batch_items WHERE batch_id=?').get(batchId).n;
    if (total > 0 && pending === 0) {
      this.db.prepare("UPDATE batches SET status='loaded' WHERE id=? AND status='scheduled'").run(batchId);
    }
  }

  findGlazeConflict(glazeA, glazeB) {
    if (glazeA === glazeB) return null;
    const a = Math.min(glazeA, glazeB);
    const b = Math.max(glazeA, glazeB);
    return this.db.prepare('SELECT * FROM glaze_conflicts WHERE glaze_a=? AND glaze_b=?').get(a, b) || null;
  }

  glazeName(id) {
    const g = this.db.prepare('SELECT name FROM glazes WHERE id=?').get(id);
    return g ? g.name : `#${id}`;
  }

  // ---------- 点火 / 冷却 / 开窑 / 清点 ----------

  /** 点火：仅管理员；点火后批次与程序锁定，计算冷却完成时点 */
  ignite(actor, batchId) {
    const batch = this.getBatch(batchId);
    if (!['loaded', 'interrupted'].includes(batch.status)) {
      throw new HttpError(409, 'BAD_STATE', `批次状态 ${batch.status}，须完成装窑（loaded）才能点火`);
    }
    const program = this.getProgram(batch.program_id);
    const { firingHours, coolingHours } = computeCurve(program);
    const now = this.now();
    const firingEnd = addHours(now, firingHours);
    const cooledUntil = addHours(firingEnd, coolingHours);
    this.db.prepare(
      `UPDATE batches SET status='firing', ignited_at=?, ignited_by=?, firing_end_at=?, cooled_until=? WHERE id=?`
    ).run(now, actor.username, firingEnd, cooledUntil, batchId);
    this.db.prepare(
      `UPDATE works SET status='firing' WHERE id IN (SELECT work_id FROM batch_items WHERE batch_id=?)`
    ).run(batchId);
    this.recordEvent('batch', batchId, 'ignited',
      `点火（${actor.username}），程序「${program.name}」锁定，预计 ${cooledUntil} 完全冷却`, actor.username);
    return this.batchDetail(batchId);
  }

  /** 进程内任务：推进 firing→cooling→cooled，并同步作品状态 */
  tick() {
    const now = this.now();
    const firingDone = this.db.prepare(
      "SELECT id FROM batches WHERE status='firing' AND firing_end_at <= ?"
    ).all(now);
    for (const b of firingDone) {
      this.db.prepare("UPDATE batches SET status='cooling' WHERE id=?").run(b.id);
      this.db.prepare(
        `UPDATE works SET status='cooling' WHERE id IN (SELECT work_id FROM batch_items WHERE batch_id=?)`
      ).run(b.id);
      this.recordEvent('batch', b.id, 'cooling_started', '烧成结束，进入自然冷却', 'system');
    }
    const cooled = this.db.prepare(
      "SELECT id FROM batches WHERE status='cooling' AND cooled_until <= ?"
    ).all(now);
    for (const b of cooled) {
      this.db.prepare("UPDATE batches SET status='cooled' WHERE id=?").run(b.id);
      this.recordEvent('batch', b.id, 'cooled', '完全冷却，可以开窑', 'system');
    }
    return { toCooling: firingDone.length, toCooled: cooled.length };
  }

  /** 开窑：完全冷却后教师可开；提前开窑仅管理员且留痕 early_open */
  openBatch(actor, batchId) {
    const batch = this.getBatch(batchId);
    if (batch.status === 'cooled') {
      this.doOpen(actor, batch, false);
    } else if (['firing', 'cooling'].includes(batch.status)) {
      if (actor.role !== 'admin') {
        throw new HttpError(403, 'EARLY_OPEN_NEEDS_ADMIN',
          `批次尚未完全冷却（${batch.cooled_until} 后方可开窑），提前开窑需要管理员权限`);
      }
      const program = this.getProgram(batch.program_id);
      const reading = readTemperature(program, batch.ignited_at, this.now());
      const remainH = Math.max(0, Math.ceil(hoursBetween(this.now(), batch.cooled_until)));
      this.recordEvent('batch', batchId, 'early_open',
        `开窑过早：距完全冷却还差约 ${remainH} 小时，窑温约 ${reading.temp_c}°C，管理员 ${actor.username} 强制开窑`, actor.username);
      this.doOpen(actor, batch, true);
    } else {
      throw new HttpError(409, 'BAD_STATE', `批次状态 ${batch.status} 不能开窑`);
    }
    return this.batchDetail(batchId);
  }

  doOpen(actor, batch, early) {
    this.db.prepare(
      "UPDATE batches SET status='opened', opened_at=?, opened_by=?, opened_early=? WHERE id=?"
    ).run(this.now(), actor.username, early ? 1 : 0, batch.id);
    this.recordEvent('batch', batch.id, 'opened', early ? '异常开窑（过早）' : '正常开窑', actor.username);
  }

  /** 出窑清点：逐件登记 完好/裂损/少件，裂损与少件留痕，全部清点完批次关闭 */
  countBatch(actor, batchId, results) {
    const batch = this.getBatch(batchId);
    if (batch.status !== 'opened') {
      throw new HttpError(409, 'BAD_STATE', `批次状态 ${batch.status}，须先开窑才能清点`);
    }
    if (!Array.isArray(results) || results.length === 0) {
      throw new HttpError(400, 'BAD_FIELD', 'results 必须是非空数组');
    }
    for (const r of results) {
      if (!['intact', 'cracked', 'missing'].includes(r.result)) {
        throw new HttpError(400, 'BAD_RESULT', '结果须为 intact / cracked / missing');
      }
      const item = this.db.prepare('SELECT * FROM batch_items WHERE batch_id=? AND work_id=?').get(batchId, r.workId);
      if (!item) throw new HttpError(404, 'ITEM_NOT_FOUND', `作品 ${r.workId} 不在批次中`);
      if (item.result !== 'pending') throw new HttpError(409, 'ALREADY_COUNTED', `作品 ${r.workId} 已清点过`);
      this.db.prepare('UPDATE batch_items SET result=?, damage_note=? WHERE id=?')
        .run(r.result, r.note || null, item.id);
      const work = this.getWork(r.workId);
      if (r.result === 'intact') {
        if (work.stage === 'bisque') {
          this.db.prepare("UPDATE works SET stage='glaze', status='awaiting_glaze' WHERE id=?").run(work.id);
          this.recordEvent('work', work.id, 'bisque_done', '素烧完好，待施釉釉烧', actor.username);
        } else {
          this.db.prepare("UPDATE works SET stage='done', status='finished' WHERE id=?").run(work.id);
          this.recordEvent('work', work.id, 'finished', '釉烧完好，作品完成', actor.username);
        }
        this.db.prepare("UPDATE refires SET status='done' WHERE work_id=? AND new_batch_id=?").run(work.id, batchId);
      } else if (r.result === 'cracked') {
        this.db.prepare("UPDATE works SET status='damaged' WHERE id=?").run(work.id);
        this.recordEvent('work', work.id, 'cracked',
          `裂损：${r.note || '出窑发现开裂'}（批次「${batch.name}」）`, actor.username);
      } else {
        this.db.prepare("UPDATE works SET status='missing' WHERE id=?").run(work.id);
        this.recordEvent('work', work.id, 'missing',
          `作品少件：出窑清点时未找到（批次「${batch.name}」）${r.note ? '：' + r.note : ''}`, actor.username);
      }
    }
    const remaining = this.db.prepare(
      "SELECT COUNT(*) AS n FROM batch_items WHERE batch_id=? AND result='pending'"
    ).get(batchId).n;
    if (remaining === 0) {
      this.db.prepare("UPDATE batches SET status='closed' WHERE id=?").run(batchId);
      this.recordEvent('batch', batchId, 'counted', '出窑清点完成，批次关闭', actor.username);
    }
    return this.batchDetail(batchId);
  }

  // ---------- 补烧 ----------

  /** 补烧：必须引用原作品与失败原因，且原批次中确有裂损记录 */
  createRefire(actor, { workId, sourceBatchId, reason }) {
    const work = this.getWork(workId);
    const source = this.getBatch(sourceBatchId);
    requireString(reason, 'reason', { maxLen: 300 });
    const item = this.db.prepare(
      "SELECT * FROM batch_items WHERE batch_id=? AND work_id=? AND result='cracked'"
    ).get(sourceBatchId, workId);
    if (!item) {
      throw new HttpError(409, 'NO_FAILURE_BASIS',
        `作品 ${work.code} 在批次「${source.name}」中没有裂损记录，不能据此补烧`);
    }
    const dup = this.db.prepare(
      "SELECT id FROM refires WHERE work_id=? AND status IN ('pending','scheduled')"
    ).all(workId);
    if (dup.length > 0) throw new HttpError(409, 'REFIRE_EXISTS', `作品 ${work.code} 已有进行中的补烧单`);

    const info = this.db.prepare(
      'INSERT INTO refires (work_id, source_batch_id, reason, created_by, created_at) VALUES (?,?,?,?,?)'
    ).run(workId, sourceBatchId, reason, actor.username, this.now());
    this.db.prepare("UPDATE works SET status='refire_pending' WHERE id=?").run(workId);
    this.recordEvent('work', workId, 'refire_created',
      `补烧单 #${Number(info.lastInsertRowid)}：引用批次「${source.name}」裂损记录，原因：${reason}`, actor.username);
    return this.refireList().find((r) => r.id === Number(info.lastInsertRowid));
  }

  // ---------- 停电（模拟适配器入口） ----------

  /** 停电中断：仅管理员；记录当前窑温并留痕 */
  powerOutage(actor, kilnId, note) {
    const kiln = this.getKiln(kilnId);
    const batch = this.db.prepare(
      "SELECT * FROM batches WHERE kiln_id=? AND status='firing'"
    ).get(kilnId);
    if (!batch) throw new HttpError(409, 'NO_ACTIVE_FIRING', `窑炉「${kiln.name}」当前没有烧制中的批次`);
    const program = this.getProgram(batch.program_id);
    const reading = readTemperature(program, batch.ignited_at, this.now());
    this.db.prepare("UPDATE batches SET status='interrupted' WHERE id=?").run(batch.id);
    this.recordEvent('batch', batch.id, 'power_outage',
      `停电中断：窑温约 ${reading.temp_c}°C 时断电。${note || ''}`.trim(), actor.username);
    this.recordEvent('kiln', kiln.id, 'power_outage', `批次「${batch.name}」中断`, actor.username);
    return this.batchDetail(batch.id);
  }

  // ---------- 查询 ----------

  workDetail(id) {
    const w = this.getWork(id);
    const student = this.db.prepare(
      'SELECT s.code, c.name AS class_name FROM students s JOIN classes c ON c.id=s.class_id WHERE s.id=?'
    ).get(w.student_id);
    const clay = this.db.prepare('SELECT name FROM clays WHERE id=?').get(w.clay_id);
    const glaze = w.glaze_id ? this.db.prepare('SELECT name, color_hex FROM glazes WHERE id=?').get(w.glaze_id) : null;
    const events = this.db.prepare(
      "SELECT * FROM events WHERE entity_type='work' AND entity_id=? ORDER BY created_at DESC, id DESC"
    ).all(id);
    const photos = this.db.prepare(
      "SELECT * FROM photos WHERE owner_type='work' AND owner_id=? ORDER BY id"
    ).all(id);
    return {
      ...w, student_code: student.code, class_name: student.class_name,
      clay_name: clay.name, glaze_name: glaze?.name ?? null, glaze_color: glaze?.color_hex ?? null,
      dry_ready: w.status === 'drying' && this.now() >= w.dry_due_at,
      events, photos,
    };
  }

  listWorks({ status } = {}) {
    const rows = this.db.prepare(
      `SELECT w.*, s.code AS student_code, c.name AS class_name, cl.name AS clay_name, g.name AS glaze_name
       FROM works w
       JOIN students s ON s.id=w.student_id
       JOIN classes c ON c.id=s.class_id
       JOIN clays cl ON cl.id=w.clay_id
       LEFT JOIN glazes g ON g.id=w.glaze_id
       ${status ? 'WHERE w.status=?' : ''} ORDER BY w.id DESC`
    ).all(...(status ? [status] : []));
    return rows.map((w) => ({ ...w, dry_ready: w.status === 'drying' && this.now() >= w.dry_due_at }));
  }

  dryingQueue() {
    const rows = this.listWorks({ status: 'drying' });
    const now = this.now();
    return rows.map((w) => ({
      ...w,
      remaining_hours: Math.max(0, Math.ceil(hoursBetween(now, w.dry_due_at) * 10) / 10),
      progress: Math.min(1, 1 - Math.max(0, hoursBetween(now, w.dry_due_at)) / w.dry_required_hours),
    }));
  }

  batchDetail(id) {
    const b = this.getBatch(id);
    const kiln = this.getKiln(b.kiln_id);
    const program = this.getProgram(b.program_id);
    const items = this.db.prepare(
      `SELECT bi.*, w.code AS work_code, w.width_mm, w.depth_mm, w.height_mm, w.stage,
              g.name AS glaze_name, g.color_hex AS glaze_color, s.code AS student_code
       FROM batch_items bi
       JOIN works w ON w.id=bi.work_id
       LEFT JOIN glazes g ON g.id=w.glaze_id
       JOIN students s ON s.id=w.student_id
       WHERE bi.batch_id=? ORDER BY bi.shelf_no, bi.id`
    ).all(id);
    const events = this.db.prepare(
      "SELECT * FROM events WHERE entity_type='batch' AND entity_id=? ORDER BY created_at DESC, id DESC"
    ).all(id);
    const photos = this.db.prepare(
      "SELECT * FROM photos WHERE owner_type='batch' AND owner_id=? ORDER BY id"
    ).all(id);
    return {
      ...b, kiln_name: kiln.name, program_name: program.name,
      kiln: { ...kiln }, program: { ...program, curve: computeCurve(program) },
      items, events, photos,
    };
  }

  listBatches({ from, to } = {}) {
    let sql = `SELECT b.*, k.name AS kiln_name, p.name AS program_name,
        (SELECT COUNT(*) FROM batch_items bi WHERE bi.batch_id=b.id) AS item_count
       FROM batches b JOIN kilns k ON k.id=b.kiln_id JOIN programs p ON p.id=b.program_id`;
    const params = [];
    if (from && to) {
      sql += ' WHERE b.scheduled_start < ? AND b.scheduled_end > ?';
      params.push(to, from);
    }
    sql += ' ORDER BY b.scheduled_start';
    return this.db.prepare(sql).all(...params);
  }

  batchLayout(batchId) {
    const detail = this.batchDetail(batchId);
    const shelves = [];
    for (let n = 1; n <= detail.kiln.shelf_count; n++) {
      shelves.push({
        shelf_no: n,
        radius_mm: detail.kiln.shelf_radius_mm,
        items: detail.items.filter((it) => it.shelf_no === n),
      });
    }
    return {
      batch: { id: detail.id, name: detail.name, status: detail.status, kind: detail.kind },
      kiln: detail.kiln,
      shelves,
      unplaced: detail.items.filter((it) => it.shelf_no == null),
    };
  }

  coolingList() {
    return this.db.prepare(
      `SELECT b.*, k.name AS kiln_name, p.name AS program_name,
        (SELECT COUNT(*) FROM batch_items bi WHERE bi.batch_id=b.id) AS item_count
       FROM batches b JOIN kilns k ON k.id=b.kiln_id JOIN programs p ON p.id=b.program_id
       WHERE b.status IN ('firing','cooling','cooled','interrupted') ORDER BY b.cooled_until`
    ).all().map((b) => ({
      ...b,
      remaining_hours: b.cooled_until ? Math.max(0, Math.ceil(hoursBetween(this.now(), b.cooled_until) * 10) / 10) : null,
    }));
  }

  refireList() {
    return this.db.prepare(
      `SELECT r.*, w.code AS work_code, sb.name AS source_batch_name, nb.name AS new_batch_name
       FROM refires r
       JOIN works w ON w.id=r.work_id
       JOIN batches sb ON sb.id=r.source_batch_id
       LEFT JOIN batches nb ON nb.id=r.new_batch_id
       ORDER BY r.id DESC`
    ).all();
  }

  kilnTemperature(kilnId) {
    const kiln = this.getKiln(kilnId);
    const batch = this.db.prepare(
      "SELECT * FROM batches WHERE kiln_id=? AND status IN ('firing','cooling','interrupted') ORDER BY id DESC LIMIT 1"
    ).get(kilnId);
    if (!batch) return { kiln: kiln.name, status: 'idle', temp_c: 25, batch: null };
    const program = this.getProgram(batch.program_id);
    const reading = readTemperature(program, batch.ignited_at, this.now());
    return {
      kiln: kiln.name, status: batch.status, batch: { id: batch.id, name: batch.name },
      ...reading,
    };
  }

  listEvents({ entityType, entityId, anomaliesOnly } = {}) {
    let sql = 'SELECT * FROM events WHERE 1=1';
    const params = [];
    if (entityType) { sql += ' AND entity_type=?'; params.push(entityType); }
    if (entityId) { sql += ' AND entity_id=?'; params.push(entityId); }
    sql += ' ORDER BY created_at DESC, id DESC LIMIT 200';
    const rows = this.db.prepare(sql).all(...params);
    return anomaliesOnly ? rows.filter((e) => ANOMALY_TYPES.has(e.type)) : rows;
  }

  /** 学生端：仅作品进度与成品照片，不暴露任何设备/批次控制信息 */
  studentView(studentCode) {
    const student = this.db.prepare(
      'SELECT s.*, c.name AS class_name FROM students s JOIN classes c ON c.id=s.class_id WHERE s.code=?'
    ).get(studentCode);
    if (!student) throw new HttpError(404, 'STUDENT_NOT_FOUND', '代号不存在');
    const works = this.db.prepare(
      `SELECT w.id, w.code, w.stage, w.status, w.width_mm, w.depth_mm, w.height_mm,
              cl.name AS clay_name, g.name AS glaze_name, g.color_hex AS glaze_color, w.created_at
       FROM works w JOIN clays cl ON cl.id=w.clay_id LEFT JOIN glazes g ON g.id=w.glaze_id
       WHERE w.student_id=? ORDER BY w.id DESC`
    ).all(student.id);
    const ids = works.map((w) => w.id);
    const photos = ids.length
      ? this.db.prepare(
          `SELECT owner_id AS work_id, path FROM photos
           WHERE owner_type='work' AND kind='product' AND owner_id IN (${ids.map(() => '?').join(',')})`
        ).all(...ids)
      : [];
    const photoMap = new Map();
    for (const p of photos) {
      if (!photoMap.has(p.work_id)) photoMap.set(p.work_id, []);
      photoMap.get(p.work_id).push(p.path);
    }
    return {
      student: { code: student.code, class_name: student.class_name },
      works: works.map((w) => ({
        ...w,
        progress: studentProgress(w),
        product_photos: photoMap.get(w.id) || [],
      })),
    };
  }
}

/** 学生端进度步骤（不含设备信息） */
function studentProgress(work) {
  const steps = ['已登记', '自然干燥', '干燥合格', '素烧', '施釉待烧', '釉烧', '完成'];
  const idx = {
    drying: 1, dry_qualified: 2, scheduled: 3, firing: 3, cooling: 3,
    awaiting_glaze: 4, finished: 6, damaged: 3, missing: 3, refire_pending: 3,
  }[work.status] ?? 0;
  const current = work.status === 'damaged' ? '裂损待补烧'
    : work.status === 'missing' ? '少件核查中'
    : work.status === 'refire_pending' ? '等待补烧'
    : steps[idx];
  return { steps, index: idx, current };
}

/** 圆形棚板槽位：中心 1 + 内环 6 + 外环 10（俯视示意） */
function ringSlots(radiusMm) {
  const slots = [{ angle: 0, radius: 0 }];
  const rings = [
    { r: radiusMm * 0.45, n: 6 },
    { r: radiusMm * 0.8, n: 10 },
  ];
  for (const ring of rings) {
    for (let i = 0; i < ring.n; i++) {
      slots.push({ angle: Math.round((360 / ring.n) * i * 10) / 10, radius: Math.round(ring.r) });
    }
  }
  return slots;
}

module.exports = { KilnService, ANOMALY_TYPES, ringSlots, studentProgress };
