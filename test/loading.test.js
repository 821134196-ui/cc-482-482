'use strict';

/** 装载约束：釉料相冲 / 装载超高 / 棚板容量，违规留痕 */
const test = require('node:test');
const assert = require('node:assert/strict');
const { makeApp, api, h, makeDryWork, makeGlazeReadyWork, eventsOf } = require('./helpers');

async function glazeBatch(app, kilnId = 1) {
  const r = await api(app.url, 'tok-teacher', 'POST', '/api/batches', {
    name: `釉烧-${Math.random()}`, kiln_id: kilnId, program_id: 2, kind: 'glaze',
    start: h(app.clock, 0), end: h(app.clock, 20),
  });
  return r.json.id;
}

test('装载约束：相冲釉色不能同层，违规留痕 glaze_conflict', async (t) => {
  const app = await makeApp();
  t.after(() => app.server.close());
  const { service, clock, db, url } = app;

  const wBlue = makeGlazeReadyWork(service, clock, 1, { student: 'S3-01' }); // 釉蓝
  const wRed = makeGlazeReadyWork(service, clock, 2, { student: 'S3-02' });  // 铁红（与釉蓝相冲）
  const batchId = await glazeBatch(app);
  await api(url, 'tok-teacher', 'POST', `/api/batches/${batchId}/items`, { work_id: wBlue });
  await api(url, 'tok-teacher', 'POST', `/api/batches/${batchId}/items`, { work_id: wRed });

  // 釉蓝放第 1 层
  let r = await api(url, 'tok-teacher', 'POST', `/api/batches/${batchId}/items/${wBlue}/position`, { shelf_no: 1 });
  assert.equal(r.status, 200);

  // 铁红强行同层 → 拒绝 + 留痕
  r = await api(url, 'tok-teacher', 'POST', `/api/batches/${batchId}/items/${wRed}/position`, { shelf_no: 1 });
  assert.equal(r.status, 409);
  assert.equal(r.json.error, 'GLAZE_CONFLICT');
  const conflicts = eventsOf(db, 'glaze_conflict');
  assert.equal(conflicts.length, 1);
  assert.match(conflicts[0].detail, /釉料相冲/);

  // 铁红放第 2 层 → 允许
  r = await api(url, 'tok-teacher', 'POST', `/api/batches/${batchId}/items/${wRed}/position`, { shelf_no: 2 });
  assert.equal(r.status, 200);

  // 自动排布会把相冲釉色分到不同层
  const wBlue2 = makeGlazeReadyWork(service, clock, 1, { student: 'S3-03' });
  const wRed2 = makeGlazeReadyWork(service, clock, 2, { student: 'S3-04' });
  const batch2 = await glazeBatch(app, 2);
  await api(url, 'tok-teacher', 'POST', `/api/batches/${batch2}/items`, { work_id: wBlue2 });
  await api(url, 'tok-teacher', 'POST', `/api/batches/${batch2}/items`, { work_id: wRed2 });
  r = await api(url, 'tok-teacher', 'POST', `/api/batches/${batch2}/auto-assign`);
  assert.equal(r.status, 200);
  const layout = r.json;
  const shelfOf = (wid) => layout.shelves.find((s) => s.items.some((it) => it.work_id === wid)).shelf_no;
  assert.notEqual(shelfOf(wBlue2), shelfOf(wRed2), '相冲釉色应自动分层');
});

test('装载约束：超高作品拒绝入层并留痕 over_height', async (t) => {
  const app = await makeApp();
  t.after(() => app.server.close());
  const { service, clock, db, url } = app;
  // 窑层净高 200mm，作品高 250mm（素烧批次同样受层高校验）
  const wTall = makeDryWork(service, clock, { student: 'S3-01', hh: 250 });
  const b = await api(url, 'tok-teacher', 'POST', '/api/batches', {
    name: '素烧超高测试', kiln_id: 1, program_id: 1, kind: 'bisque',
    start: h(app.clock, 0), end: h(app.clock, 20),
  });
  const batchId = b.json.id;
  await api(url, 'tok-teacher', 'POST', `/api/batches/${batchId}/items`, { work_id: wTall });

  const r = await api(url, 'tok-teacher', 'POST', `/api/batches/${batchId}/items/${wTall}/position`, { shelf_no: 1 });
  assert.equal(r.status, 409);
  assert.equal(r.json.error, 'OVER_HEIGHT');
  assert.equal(eventsOf(db, 'over_height').length, 1);

  const r2 = await api(url, 'tok-teacher', 'POST', `/api/batches/${batchId}/auto-assign`);
  assert.equal(r2.status, 409, '自动排布同样拦截超高');
  assert.equal(r2.json.error, 'OVER_HEIGHT');
});

test('装载约束：棚板容量上限', async (t) => {
  const app = await makeApp();
  t.after(() => app.server.close());
  const { service, clock, url } = app;
  // 窑A 每层 3 件
  const works = [1, 2, 3, 4].map((i) => makeGlazeReadyWork(service, clock, 3, { student: `S3-0${i}` }));
  const batchId = await glazeBatch(app);
  for (const w of works) await api(url, 'tok-teacher', 'POST', `/api/batches/${batchId}/items`, { work_id: w });
  for (let i = 0; i < 3; i++) {
    const r = await api(url, 'tok-teacher', 'POST', `/api/batches/${batchId}/items/${works[i]}/position`, { shelf_no: 1 });
    assert.equal(r.status, 200, `第 ${i + 1} 件应放入`);
  }
  const r = await api(url, 'tok-teacher', 'POST', `/api/batches/${batchId}/items/${works[3]}/position`, { shelf_no: 1 });
  assert.equal(r.status, 409);
  assert.equal(r.json.error, 'SHELF_FULL');
});
