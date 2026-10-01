'use strict';

/** 作品唯一：同一作品不能同时处于两个未结束批次 */
const test = require('node:test');
const assert = require('node:assert/strict');
const { makeApp, api, h, makeDryWork, makeGlazeReadyWork } = require('./helpers');

async function bisqueBatch(app, kilnId, startH, endH, name) {
  const r = await api(app.url, 'tok-teacher', 'POST', '/api/batches', {
    name, kiln_id: kilnId, program_id: 1, kind: 'bisque',
    start: h(app.clock, startH), end: h(app.clock, endH),
  });
  assert.equal(r.status, 200, r.json.message);
  return r.json.id;
}

test('作品唯一：未结束批次中的作品不能再次入窑', async (t) => {
  const app = await makeApp();
  t.after(() => app.server.close());
  const { service, clock, url } = app;
  const workId = makeDryWork(service, clock, { student: 'S3-01', glazeId: 1 });

  const b1 = await bisqueBatch(app, 1, 0, 20, '批次一');
  let r = await api(url, 'tok-teacher', 'POST', `/api/batches/${b1}/items`, { work_id: workId });
  assert.equal(r.status, 200);

  // 同一批次重复加入
  r = await api(url, 'tok-teacher', 'POST', `/api/batches/${b1}/items`, { work_id: workId });
  assert.equal(r.status, 409);

  // 另一窑炉、不重叠时段的批次也不能加入同一作品
  const b2 = await bisqueBatch(app, 2, 30, 50, '批次二');
  r = await api(url, 'tok-teacher', 'POST', `/api/batches/${b2}/items`, { work_id: workId });
  assert.equal(r.status, 409);
  assert.equal(r.json.error, 'WORK_BUSY');

  // 走完批次一（点火→冷却→开窑→清点）后，作品可进入下一阶段批次
  await api(url, 'tok-teacher', 'POST', `/api/batches/${b1}/auto-assign`);
  await api(url, 'tok-admin', 'POST', `/api/batches/${b1}/ignite`);
  clock.advanceHours(16);
  service.tick();
  await api(url, 'tok-teacher', 'POST', `/api/batches/${b1}/open`);
  r = await api(url, 'tok-teacher', 'POST', `/api/batches/${b1}/count`, {
    results: [{ work_id: workId, result: 'intact' }],
  });
  assert.equal(r.status, 200);
  assert.equal(r.json.status, 'closed');

  // 素烧完好 → 待釉烧，可加入釉烧批次
  const glaze = await api(url, 'tok-teacher', 'POST', '/api/batches', {
    name: '釉烧批次', kiln_id: 1, program_id: 2, kind: 'glaze',
    start: h(clock, 30), end: h(clock, 50),
  });
  r = await api(url, 'tok-teacher', 'POST', `/api/batches/${glaze.json.id}/items`, { work_id: workId });
  assert.equal(r.status, 200, '已结束批次释放作品，可进入釉烧');
});

test('作品唯一：批次取消后作品被释放', async (t) => {
  const app = await makeApp();
  t.after(() => app.server.close());
  const { service, clock, url } = app;
  const workId = makeDryWork(service, clock, { student: 'S3-02' });
  const b1 = await bisqueBatch(app, 1, 0, 20, '将取消');
  await api(url, 'tok-teacher', 'POST', `/api/batches/${b1}/items`, { work_id: workId });
  await api(url, 'tok-teacher', 'POST', `/api/batches/${b1}/cancel`);

  const b2 = await bisqueBatch(app, 2, 0, 20, '接收批次');
  const r = await api(url, 'tok-teacher', 'POST', `/api/batches/${b2}/items`, { work_id: workId });
  assert.equal(r.status, 200, '取消批次后作品可重新排入');
});

test('作品资格：未干燥合格不能排入素烧', async (t) => {
  const app = await makeApp();
  t.after(() => app.server.close());
  const { url } = app;
  // 直接登记，不等待干燥
  const w = await api(url, 'tok-teacher', 'POST', '/api/works', {
    student_code: 'S3-03', clay_id: 1, width_mm: 100, depth_mm: 100, height_mm: 100,
  });
  assert.equal(w.status, 200);
  const b1 = await bisqueBatch(app, 1, 0, 20, '素烧');
  const r = await api(url, 'tok-teacher', 'POST', `/api/batches/${b1}/items`, { work_id: w.json.id });
  assert.equal(r.status, 409);
  assert.equal(r.json.error, 'WORK_NOT_ELIGIBLE');
});

test('补烧作品唯一性：补烧单排入新批次后仍受唯一约束', async (t) => {
  const app = await makeApp();
  t.after(() => app.server.close());
  const { service, clock, url } = app;
  // 走完釉烧并判定裂损 → 创建补烧单
  const workId = makeGlazeReadyWork(service, clock, 3, { student: 'S3-04' });
  const g1 = await api(url, 'tok-teacher', 'POST', '/api/batches', {
    name: '釉烧一', kiln_id: 1, program_id: 2, kind: 'glaze', start: h(clock, 0), end: h(clock, 20),
  });
  await api(url, 'tok-teacher', 'POST', `/api/batches/${g1.json.id}/items`, { work_id: workId });
  await api(url, 'tok-teacher', 'POST', `/api/batches/${g1.json.id}/auto-assign`);
  await api(url, 'tok-admin', 'POST', `/api/batches/${g1.json.id}/ignite`);
  clock.advanceHours(16);
  service.tick();
  await api(url, 'tok-teacher', 'POST', `/api/batches/${g1.json.id}/open`);
  await api(url, 'tok-teacher', 'POST', `/api/batches/${g1.json.id}/count`, {
    results: [{ work_id: workId, result: 'cracked', note: '肩部开裂' }],
  });
  const rf = await api(url, 'tok-teacher', 'POST', '/api/refires', {
    work_id: workId, source_batch_id: g1.json.id, reason: '肩部开裂，修坯补烧',
  });
  assert.equal(rf.status, 200);

  // 排入补烧批次
  const g2 = await api(url, 'tok-teacher', 'POST', '/api/batches', {
    name: '补烧窑', kiln_id: 2, program_id: 2, kind: 'glaze', start: h(clock, 30), end: h(clock, 50),
  });
  let r = await api(url, 'tok-teacher', 'POST', `/api/batches/${g2.json.id}/items`, { work_id: workId });
  assert.equal(r.status, 200);
  const refires = (await api(url, 'tok-teacher', 'GET', '/api/refires')).json;
  assert.equal(refires[0].status, 'scheduled');
  assert.equal(refires[0].new_batch_id, g2.json.id);

  // 同时不能再进别的批次
  const g3 = await api(url, 'tok-teacher', 'POST', '/api/batches', {
    name: '另一釉烧', kiln_id: 1, program_id: 2, kind: 'glaze', start: h(clock, 60), end: h(clock, 80),
  });
  r = await api(url, 'tok-teacher', 'POST', `/api/batches/${g3.json.id}/items`, { work_id: workId });
  assert.equal(r.status, 409);
  assert.equal(r.json.error, 'WORK_BUSY');
});
