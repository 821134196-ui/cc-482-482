'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { KilnService } = require('./services');
const { manualClock } = require('./clock');

/**
 * 种子数据：用手动时钟从 9 天前开始“时间旅行”，
 * 通过服务层真实走完整条链路（登记→干燥→素烧→釉烧→清点），
 * 因此釉料相冲、停电中断、开窑过早、裂损、补烧等留痕都是真实生成的。
 */
function seedIfEmpty(db, photoDir) {
  const count = db.prepare('SELECT COUNT(*) AS n FROM users').get().n;
  if (count > 0) return false;

  const clock = manualClock(new Date(Date.now() - 9 * 24 * 3600e3).toISOString());
  const svc = new KilnService({ db, clock, photoDir });
  const admin = { username: 'admin', role: 'admin' };
  const teacher = { username: 'teacher', role: 'teacher' };
  const H = 3600e3;
  const at = (h) => new Date(Date.now() + h * H).toISOString(); // 相对真实现在的小时偏移
  const jump = (h) => clock.set(at(h));

  // ---------- 基础档案 ----------
  db.prepare("INSERT INTO users (username, display_name, role) VALUES ('admin','窑房管理员','admin')").run();
  db.prepare("INSERT INTO users (username, display_name, role) VALUES ('teacher','陶艺老师','teacher')").run();
  db.prepare("INSERT INTO tokens (token, user_id) VALUES ('tok-admin',1),('tok-teacher',2)").run();
  db.prepare("INSERT INTO classes (name) VALUES ('三年级1班'),('四年级2班')").run();
  const insStudent = db.prepare('INSERT INTO students (class_id, code) VALUES (?,?)');
  for (let i = 1; i <= 6; i++) insStudent.run(1, `S3-0${i}`);
  for (let i = 1; i <= 6; i++) insStudent.run(2, `S4-0${i}`);

  db.prepare("INSERT INTO clays (name, dry_hours_base, note) VALUES ('陶泥',24,'常用红陶'),('瓷泥',36,'干燥较慢'),('粗陶',20,'颗粒粗、干得快')").run();
  const insGlaze = db.prepare('INSERT INTO glazes (name, color_hex, note) VALUES (?,?,?)');
  insGlaze.run('透明釉', '#dfe9ec', '本色透明');
  insGlaze.run('釉蓝', '#2f6f8f', '蓝色系');
  insGlaze.run('窑火橙', '#e2601a', '橙色系');
  insGlaze.run('青釉', '#7fb069', '青绿色');
  insGlaze.run('铁红', '#8c3b2e', '含铁，易挥发污染');
  insGlaze.run('无光白', '#efe9df', '哑光白');
  // 釉料相冲样例
  db.prepare("INSERT INTO glaze_conflicts (glaze_a, glaze_b, reason) VALUES (2,5,'铁红挥发会污染釉蓝发色'),(3,6,'窑火橙与无光白同层会相互串色')").run();

  db.prepare("INSERT INTO kilns (name, shelf_count, shelf_radius_mm, shelf_gap_mm, shelf_slot_capacity, max_temp_c) VALUES ('窑炉一号',3,300,220,12,1300),('窑炉二号',4,400,260,17,1300)").run();
  const bisqueSteps = JSON.stringify([
    { ramp: 120, target: 600, hold: 15 },
    { ramp: 150, target: 900, hold: 30 },
  ]);
  const glazeSteps = JSON.stringify([
    { ramp: 150, target: 500, hold: 10 },
    { ramp: 180, target: 1000, hold: 15 },
    { ramp: 120, target: 1180, hold: 20 },
  ]);
  db.prepare("INSERT INTO programs (name, kind, steps_json, cool_rate_c_per_h) VALUES ('素烧曲线 900°C','bisque',?,100),('釉烧曲线 1180°C','glaze',?,100)").run(bisqueSteps, glazeSteps);

  const reg = (student, clay, glaze, w, d, h) =>
    svc.registerWork(teacher, { studentCode: student, clayId: clay, glazeId: glaze, widthMm: w, depthMm: d, heightMm: h }).id;
  const code = (id) => db.prepare('SELECT code FROM works WHERE id=?').get(id).code;

  // ---------- 9 天前：登记一批作品（将走完素烧+釉烧全链路） ----------
  jump(-216);
  const W11 = reg('S3-01', 1, 2, 120, 120, 150); // 釉蓝 → 成品
  const W12 = reg('S4-05', 1, 3, 110, 110, 130); // 窑火橙 → 成品
  const W13 = reg('S4-06', 1, 4, 100, 100, 140); // 青釉 → 裂损 → 补烧样例
  const W14 = reg('S3-02', 1, 6, 90, 90, 110);   // 无光白 → 少件样例
  const W17 = reg('S3-05', 1, 1, 100, 100, 120); // 透明釉 → 冷却中
  const W8 = reg('S4-03', 1, 2, 120, 110, 140);  // 釉蓝 → 待釉烧（相冲演示）
  const W9 = reg('S3-06', 1, 5, 100, 100, 130);  // 铁红 → 待釉烧（相冲演示）
  const W10 = reg('S4-04', 1, 1, 95, 95, 115);   // 透明釉 → 待釉烧
  const W20 = reg('S3-04', 1, 2, 105, 105, 125); // 釉蓝 → 自由可排
  const W21 = reg('S4-01', 1, 5, 100, 95, 120);  // 铁红 → 自由可排

  // ---------- 8 天前：干燥合格，第 2 窑素烧 ----------
  jump(-186);
  for (const id of [W11, W12, W13, W14, W17, W8, W9, W10, W20, W21]) svc.confirmDry(teacher, id);
  const B0 = svc.createBatch(teacher, {
    name: '第2窑·素烧', kilnId: 2, programId: 1, kind: 'bisque', start: at(-186), end: at(-168),
  }).id;
  for (const id of [W11, W12, W13, W14, W17, W8, W9, W10, W20, W21]) svc.addWorkToBatch(teacher, B0, id);
  svc.autoAssign(teacher, B0);
  svc.ignite(admin, B0);

  jump(-169); // 越过 firing+cooling
  svc.tick();
  svc.openBatch(teacher, B0);
  svc.countBatch(teacher, B0, [W11, W12, W13, W14, W17, W8, W9, W10, W20, W21]
    .map((id) => ({ workId: id, result: 'intact' })));

  // ---------- 7 天前：第 3 窑釉烧（开窑过早 + 裂损 + 少件） ----------
  jump(-168);
  const B1 = svc.createBatch(teacher, {
    name: '第3窑·釉烧', kilnId: 2, programId: 2, kind: 'glaze', start: at(-168), end: at(-148),
  }).id;
  for (const id of [W11, W12, W13, W14]) svc.addWorkToBatch(teacher, B1, id);
  svc.autoAssign(teacher, B1);
  svc.ignite(admin, B1);

  jump(-158); // 冷却未结束，管理员强制开窑 → early_open 留痕
  svc.openBatch(admin, B1);
  svc.countBatch(teacher, B1, [
    { workId: W11, result: 'intact' },
    { workId: W12, result: 'intact' },
    { workId: W13, result: 'cracked', note: '底足纵向开裂，疑因开窑过早遇冷' },
    { workId: W14, result: 'missing', note: '清点时未找到，已通知班级核对' },
  ]);
  // 补烧样例：引用原作品与失败原因
  svc.createRefire(teacher, { workId: W13, sourceBatchId: B1, reason: '底足开裂（开窑过早遇冷），修坯后补烧' });

  // 装窑与成品照片（本地 SVG 样例）
  writePhoto(db, photoDir, 'batch', B1, 'loading', loadingSvg('第3窑·釉烧', [code(W11), code(W12), code(W13), code(W14)]), clock.now(), 'teacher');
  writePhoto(db, photoDir, 'work', W11, 'product', productSvg(code(W11), '#2f6f8f'), clock.now(), 'teacher');
  writePhoto(db, photoDir, 'work', W12, 'product', productSvg(code(W12), '#e2601a'), clock.now(), 'teacher');

  // ---------- 3 天前 ~ 现在：停电中断样例 ----------
  jump(-72);
  const W18 = reg('S4-01', 1, null, 110, 110, 110);
  jump(-41);
  svc.confirmDry(teacher, W18);
  const B4 = svc.createBatch(teacher, {
    name: '第6窑·素烧', kilnId: 1, programId: 1, kind: 'bisque', start: at(-40), end: at(-24),
  }).id;
  svc.addWorkToBatch(teacher, B4, W18);
  svc.autoAssign(teacher, B4);
  jump(-40);
  svc.ignite(admin, B4);
  jump(-37);
  svc.powerOutage(admin, 1, '校区线路检修，断电 40 分钟'); // 停电中断留痕

  // ---------- 昨天：第 5 窑釉烧（现在仍在冷却） ----------
  jump(-20);
  const B3 = svc.createBatch(teacher, {
    name: '第5窑·釉烧', kilnId: 2, programId: 2, kind: 'glaze', start: at(-16), end: at(4),
  }).id;
  svc.addWorkToBatch(teacher, B3, W17);
  svc.autoAssign(teacher, B3);
  jump(-16);
  svc.ignite(admin, B3); // 完全冷却约在 3.7 小时后

  // ---------- 近两天：干燥队列与待排期作品 ----------
  jump(-48);
  const W22 = reg('S3-03', 1, null, 130, 130, 250); // 超高样例（250mm > 220mm 层净高）
  const W5 = reg('S3-04', 1, null, 110, 110, 120);
  const W6 = reg('S4-02', 2, null, 100, 100, 105);
  const W7 = reg('S3-05', 3, null, 95, 95, 100);
  jump(-40);
  const W15 = reg('S3-04', 3, null, 140, 130, 140);
  const W16 = reg('S4-02', 3, null, 130, 130, 135);
  const W19 = reg('S3-03', 3, null, 90, 90, 90);
  jump(-30);
  const W1 = reg('S3-01', 1, null, 120, 120, 150); // 刚好干燥达标
  jump(-26);
  reg('S3-03', 1, null, 60, 60, 60);               // 约 2 小时后达标
  jump(-19);
  reg('S4-01', 3, null, 90, 90, 80);               // 约 5 小时后达标
  jump(-14);
  svc.confirmDry(teacher, W22);
  svc.confirmDry(teacher, W15);
  svc.confirmDry(teacher, W16);
  svc.confirmDry(teacher, W19);
  jump(-10);
  const W2 = reg('S3-02', 2, null, 100, 100, 200); // 瓷泥大件，远未达标
  jump(-6);
  svc.reportLabelLost(teacher, W2, '搬运时标签碰落，已补贴并拍照存档'); // 标签脱落留痕
  try { svc.confirmDry(teacher, W2); } catch { /* 干燥不足 → dry_insufficient 留痕 */ }

  // ---------- 当前：点火中的第 4 窑 + 未来排期 ----------
  jump(-5);
  svc.confirmDry(teacher, W5);
  svc.confirmDry(teacher, W6);
  svc.confirmDry(teacher, W7);
  const B2 = svc.createBatch(teacher, {
    name: '第4窑·素烧', kilnId: 1, programId: 1, kind: 'bisque', start: at(-3), end: at(14),
  }).id;
  svc.addWorkToBatch(teacher, B2, W15);
  svc.addWorkToBatch(teacher, B2, W16);
  svc.autoAssign(teacher, B2);
  jump(-3);
  svc.ignite(admin, B2); // 现在正在烧制，窑温实时可读

  const B5 = svc.createBatch(teacher, {
    name: '第7窑·素烧', kilnId: 1, programId: 1, kind: 'bisque', start: at(24), end: at(40),
  }).id;
  svc.addWorkToBatch(teacher, B5, W19);
  svc.autoAssign(teacher, B5);
  // 装载超高留痕：W22 超过窑炉一号层间净高
  svc.addWorkToBatch(teacher, B5, W22);
  try { svc.assignPosition(teacher, B5, W22, 1, 0, 0); } catch { /* over_height 留痕 */ }
  svc.removeWorkFromBatch(teacher, B5, W22);

  // 第 8 窑釉烧：釉料相冲留痕 + 自动分层
  const B6 = svc.createBatch(teacher, {
    name: '第8窑·釉烧', kilnId: 2, programId: 2, kind: 'glaze', start: at(48), end: at(64),
  }).id;
  svc.addWorkToBatch(teacher, B6, W8);
  svc.addWorkToBatch(teacher, B6, W9);
  svc.addWorkToBatch(teacher, B6, W10);
  svc.assignPosition(teacher, B6, W8, 1, 0, 0);
  try { svc.assignPosition(teacher, B6, W9, 1, 60, 120); } catch { /* glaze_conflict 留痕 */ }
  svc.autoAssign(teacher, B6);

  jump(0);
  svc.tick();
  return true;
}

function writePhoto(db, photoDir, ownerType, ownerId, kind, svg, createdAt, actor) {
  fs.mkdirSync(photoDir, { recursive: true });
  const fname = `seed-${ownerType}-${ownerId}-${kind}.svg`;
  fs.writeFileSync(path.join(photoDir, fname), svg);
  db.prepare(
    'INSERT INTO photos (owner_type, owner_id, kind, path, uploaded_by, created_at) VALUES (?,?,?,?,?,?)'
  ).run(ownerType, ownerId, kind, `/photos/${fname}`, actor, createdAt);
}

/** 成品照片样例：釉色花瓶剪影 + 作品代号 */
function productSvg(code, glazeColor) {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="480" height="360" viewBox="0 0 480 360">
  <rect width="480" height="360" fill="#f7f2ea"/>
  <ellipse cx="240" cy="318" rx="130" ry="14" fill="#e5dccb"/>
  <path d="M192 318 Q178 230 208 176 Q220 154 220 118 L260 118 Q260 154 272 176 Q302 230 288 318 Z" fill="${glazeColor}"/>
  <rect x="216" y="104" width="48" height="16" rx="4" fill="${glazeColor}"/>
  <text x="240" y="348" text-anchor="middle" font-family="sans-serif" font-size="18" fill="#6b5d4f">${code}</text>
</svg>`;
}

/** 装窑照片样例：圆形棚板俯视 */
function loadingSvg(title, codes) {
  const blocks = codes.map((c, i) => {
    const angle = (i / codes.length) * 2 * Math.PI - Math.PI / 2;
    const x = 240 + Math.cos(angle) * 95;
    const y = 200 + Math.sin(angle) * 95;
    return `<rect x="${x - 26}" y="${y - 18}" width="52" height="36" rx="5" fill="#2f6f8f" opacity="0.85"/>
    <text x="${x}" y="${y + 4}" text-anchor="middle" font-family="sans-serif" font-size="11" fill="#fff">${c}</text>`;
  }).join('\n  ');
  return `<svg xmlns="http://www.w3.org/2000/svg" width="480" height="400" viewBox="0 0 480 400">
  <rect width="480" height="400" fill="#f7f2ea"/>
  <circle cx="240" cy="200" r="150" fill="#efe6d8" stroke="#c9b99a" stroke-width="3"/>
  <circle cx="240" cy="200" r="150" fill="none" stroke="#e2601a" stroke-width="2" stroke-dasharray="6 6"/>
  ${blocks}
  <text x="240" y="385" text-anchor="middle" font-family="sans-serif" font-size="16" fill="#6b5d4f">${title} 装窑俯视</text>
</svg>`;
}

module.exports = { seedIfEmpty };
