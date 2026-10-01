'use strict';

const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { openDb } = require('../src/db');
const { KilnService } = require('../src/services');
const { manualClock } = require('../src/clock');
const { createServer } = require('../src/server');
const { addHours } = require('../src/util');

const T0 = '2026-09-30T08:00:00.000Z';
const ADMIN = { username: 'admin', role: 'admin' };
const TEACHER = { username: 'teacher', role: 'teacher' };

/** 固定装置：2 窑（层净高 200mm、每层 3 件）、3 釉（釉蓝×铁红相冲）、素/釉烧程序 */
function seedFixtures(db) {
  db.prepare("INSERT INTO users (username, display_name, role) VALUES ('admin','管理员','admin'),('teacher','教师','teacher')").run();
  db.prepare("INSERT INTO tokens (token, user_id) VALUES ('tok-admin',1),('tok-teacher',2)").run();
  db.prepare("INSERT INTO classes (name) VALUES ('三年级1班')").run();
  db.prepare("INSERT INTO students (class_id, code) VALUES (1,'S3-01'),(1,'S3-02'),(1,'S3-03'),(1,'S3-04'),(1,'S3-05'),(1,'S3-06')").run();
  db.prepare("INSERT INTO clays (name, dry_hours_base) VALUES ('陶泥',24)").run();
  db.prepare("INSERT INTO glazes (name, color_hex) VALUES ('釉蓝','#2f6f8f'),('铁红','#8c3b2e'),('透明釉','#dfe9ec')").run();
  db.prepare("INSERT INTO glaze_conflicts (glaze_a, glaze_b, reason) VALUES (1,2,'铁红污染釉蓝')").run();
  db.prepare("INSERT INTO kilns (name, shelf_count, shelf_radius_mm, shelf_gap_mm, shelf_slot_capacity, max_temp_c) VALUES ('窑A',2,300,200,3,1300),('窑B',2,300,200,3,1300)").run();
  // 烧成 7.75h + 冷却 7.75h（峰值 800°C）
  const steps = JSON.stringify([{ ramp: 100, target: 500, hold: 0 }, { ramp: 100, target: 800, hold: 0 }]);
  db.prepare("INSERT INTO programs (name, kind, steps_json, cool_rate_c_per_h) VALUES ('素烧P','bisque',?,100),('釉烧P','glaze',?,100)").run(steps, steps);
}

async function makeApp() {
  const clock = manualClock(T0);
  const db = openDb(':memory:');
  seedFixtures(db);
  const photoDir = fs.mkdtempSync(path.join(os.tmpdir(), 'kiln-photos-'));
  const service = new KilnService({ db, clock, photoDir });
  const server = createServer({ db, service, publicDir: path.join(__dirname, '..', 'public'), photoDir });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${server.address().port}`;
  return { db, service, clock, server, url, photoDir, ADMIN, TEACHER };
}

async function api(url, token, method, path, body) {
  const headers = {};
  if (token) headers.authorization = `Bearer ${token}`;
  if (body !== undefined) headers['content-type'] = 'application/json';
  const res = await fetch(url + path, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
  const json = await res.json().catch(() => ({}));
  return { status: res.status, json };
}

const h = (clock, hours) => addHours(clock.now(), hours);

/** 快速造一件干燥合格的作品（登记→拨快时钟→确认） */
function makeDryWork(service, clock, { student = 'S3-01', glazeId = null, w = 100, d = 100, hh = 100 } = {}) {
  const work = service.registerWork(TEACHER, {
    studentCode: student, clayId: 1, glazeId, widthMm: w, depthMm: d, heightMm: hh,
  });
  clock.advanceHours(work.dry_required_hours + 1);
  service.confirmDry(TEACHER, work.id);
  return work.id;
}

/** 把一件作品走完素烧，变为待釉烧（awaiting_glaze） */
function makeGlazeReadyWork(service, clock, glazeId, opts = {}) {
  const workId = makeDryWork(service, clock, { glazeId, ...opts });
  const batch = service.createBatch(TEACHER, {
    name: `素烧-${workId}`, kilnId: 1, programId: 1, kind: 'bisque',
    start: h(clock, 0), end: h(clock, 20),
  });
  service.addWorkToBatch(TEACHER, batch.id, workId);
  service.autoAssign(TEACHER, batch.id);
  service.ignite(ADMIN, batch.id);
  clock.advanceHours(16); // 越过 7.75h 烧成 + 7.75h 冷却
  service.tick();
  service.openBatch(TEACHER, batch.id);
  service.countBatch(TEACHER, batch.id, [{ workId, result: 'intact' }]);
  return workId;
}

/** 造一个已装窑并点火的批次，返回批次 id */
let batchSeq = 0;
function makeFiringBatch(service, clock, { kilnId = 1, programId = 1, kind = 'bisque' } = {}) {
  const workId = kind === 'bisque' ? makeDryWork(service, clock, {}) : makeGlazeReadyWork(service, clock, 3);
  const batch = service.createBatch(TEACHER, {
    name: `firing-${++batchSeq}`, kilnId, programId, kind,
    start: h(clock, 0), end: h(clock, 20),
  });
  service.addWorkToBatch(TEACHER, batch.id, workId);
  service.autoAssign(TEACHER, batch.id);
  service.ignite(ADMIN, batch.id);
  return { batchId: batch.id, workId };
}

function eventsOf(db, type) {
  return db.prepare('SELECT * FROM events WHERE type=?').all(type);
}

module.exports = { makeApp, api, h, makeDryWork, makeGlazeReadyWork, makeFiringBatch, eventsOf, ADMIN, TEACHER, T0 };
