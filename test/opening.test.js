'use strict';

/** 开窑阻断：未完全冷却教师不可开窑；管理员提前开窑留痕 early_open */
const test = require('node:test');
const assert = require('node:assert/strict');
const { makeApp, api, makeFiringBatch, eventsOf } = require('./helpers');

test('开窑阻断：冷却中教师开窑被拒，管理员提前开窑留痕', async (t) => {
  const app = await makeApp();
  t.after(() => app.server.close());
  const { clock, db, url } = app;
  const { batchId } = makeFiringBatch(app.service, clock);

  // 推进到冷却段（烧成 7.75h，冷却共 7.75h）
  clock.advanceHours(8);
  app.service.tick();
  let detail = (await api(url, 'tok-teacher', 'GET', `/api/batches/${batchId}`)).json;
  assert.equal(detail.status, 'cooling');

  // 教师提前开窑 → 403
  let r = await api(url, 'tok-teacher', 'POST', `/api/batches/${batchId}/open`);
  assert.equal(r.status, 403);
  assert.equal(r.json.error, 'EARLY_OPEN_NEEDS_ADMIN');

  // 管理员提前开窑 → 允许但留痕 early_open
  r = await api(url, 'tok-admin', 'POST', `/api/batches/${batchId}/open`);
  assert.equal(r.status, 200);
  assert.equal(r.json.opened_early, 1);
  const early = eventsOf(db, 'early_open');
  assert.equal(early.length, 1);
  assert.match(early[0].detail, /开窑过早/);
});

test('开窑阻断：完全冷却后教师可正常开窑', async (t) => {
  const app = await makeApp();
  t.after(() => app.server.close());
  const { clock, db, url } = app;
  const { batchId } = makeFiringBatch(app.service, clock);

  clock.advanceHours(16); // 越过 firing+cooling
  app.service.tick();
  const detail = (await api(url, 'tok-teacher', 'GET', `/api/batches/${batchId}`)).json;
  assert.equal(detail.status, 'cooled');

  const r = await api(url, 'tok-teacher', 'POST', `/api/batches/${batchId}/open`);
  assert.equal(r.status, 200);
  assert.equal(r.json.opened_early, 0);
  assert.equal(eventsOf(db, 'early_open').length, 0, '正常开窑不应留异常痕');
});

test('开窑阻断：烧制中同样禁止教师开窑', async (t) => {
  const app = await makeApp();
  t.after(() => app.server.close());
  const { clock, url } = app;
  const { batchId } = makeFiringBatch(app.service, clock);
  clock.advanceHours(2); // 仍在烧成段
  app.service.tick();
  const r = await api(url, 'tok-teacher', 'POST', `/api/batches/${batchId}/open`);
  assert.equal(r.status, 403);
});
