'use strict';

/** 链路留痕：干燥不足 / 标签脱落 / 停电中断 / 补烧引用 / 少件 */
const test = require('node:test');
const assert = require('node:assert/strict');
const { makeApp, api, h, makeDryWork, makeGlazeReadyWork, makeFiringBatch, eventsOf } = require('./helpers');

test('干燥：未达标确认被拒绝并留痕 dry_insufficient，达标后放行', async (t) => {
  const app = await makeApp();
  t.after(() => app.server.close());
  const { clock, db, url } = app;
  const w = await api(url, 'tok-teacher', 'POST', '/api/works', {
    student_code: 'S3-01', clay_id: 1, width_mm: 120, depth_mm: 120, height_mm: 150,
  });
  assert.equal(w.status, 200);
  assert.equal(w.json.status, 'drying');
  assert.ok(w.json.dry_required_hours >= 28, '干燥时长应由泥料与尺寸计算');

  // 未达标确认 → 409 + 留痕
  let r = await api(url, 'tok-teacher', 'POST', `/api/works/${w.json.id}/confirm-dry`);
  assert.equal(r.status, 409);
  assert.equal(r.json.error, 'DRY_INSUFFICIENT');
  assert.equal(eventsOf(db, 'dry_insufficient').length, 1);

  // 拨快时钟到达标时点 → 确认成功
  clock.advanceHours(w.json.dry_required_hours + 1);
  r = await api(url, 'tok-teacher', 'POST', `/api/works/${w.json.id}/confirm-dry`);
  assert.equal(r.status, 200);
  assert.equal(r.json.status, 'dry_qualified');
});

test('留痕：标签脱落可上报', async (t) => {
  const app = await makeApp();
  t.after(() => app.server.close());
  const { service, clock, db, url } = app;
  const workId = makeDryWork(service, clock, {});
  const r = await api(url, 'tok-teacher', 'POST', `/api/works/${workId}/label-lost`, { note: '搬运碰落' });
  assert.equal(r.status, 200);
  const ev = eventsOf(db, 'label_lost');
  assert.equal(ev.length, 1);
  assert.match(ev[0].detail, /搬运碰落/);
});

test('停电中断：留痕 power_outage，批次可恢复重新点火', async (t) => {
  const app = await makeApp();
  t.after(() => app.server.close());
  const { service, clock, db, url } = app;
  const { batchId } = makeFiringBatch(service, clock);
  clock.advanceHours(3);

  const r = await api(url, 'tok-admin', 'POST', '/api/kilns/1/power-outage', { note: '线路检修' });
  assert.equal(r.status, 200);
  assert.equal(r.json.status, 'interrupted');
  const ev = eventsOf(db, 'power_outage');
  assert.ok(ev.length >= 1);
  assert.match(ev[0].detail, /停电中断/);
  assert.match(ev[0].detail, /°C/, '留痕应包含断电时窑温');

  // 恢复供电后管理员重新点火
  const r2 = await api(url, 'tok-admin', 'POST', `/api/batches/${batchId}/ignite`);
  assert.equal(r2.status, 200);
  assert.equal(r2.json.status, 'firing');
});

test('补烧：必须引用原作品与失败原因，无裂损记录不能补烧', async (t) => {
  const app = await makeApp();
  t.after(() => app.server.close());
  const { service, clock, url } = app;
  const workId = makeGlazeReadyWork(service, clock, 3, { student: 'S3-02' });

  // 无裂损记录 → 拒绝
  let r = await api(url, 'tok-teacher', 'POST', '/api/refires', {
    work_id: workId, source_batch_id: 1, reason: '想再烧一次',
  });
  assert.equal(r.status, 409);
  assert.equal(r.json.error, 'NO_FAILURE_BASIS');

  // 走完釉烧并判裂损
  const g = await api(url, 'tok-teacher', 'POST', '/api/batches', {
    name: '釉烧', kiln_id: 1, program_id: 2, kind: 'glaze', start: h(clock, 0), end: h(clock, 20),
  });
  await api(url, 'tok-teacher', 'POST', `/api/batches/${g.json.id}/items`, { work_id: workId });
  await api(url, 'tok-teacher', 'POST', `/api/batches/${g.json.id}/auto-assign`);
  await api(url, 'tok-admin', 'POST', `/api/batches/${g.json.id}/ignite`);
  clock.advanceHours(16);
  service.tick();
  await api(url, 'tok-teacher', 'POST', `/api/batches/${g.json.id}/open`);
  await api(url, 'tok-teacher', 'POST', `/api/batches/${g.json.id}/count`, {
    results: [{ work_id: workId, result: 'cracked', note: '底足开裂' }],
  });

  // 缺原因 → 400
  r = await api(url, 'tok-teacher', 'POST', '/api/refires', {
    work_id: workId, source_batch_id: g.json.id, reason: '',
  });
  assert.equal(r.status, 400);

  // 引用原作品 + 失败原因 → 创建成功，作品进入待补烧
  r = await api(url, 'tok-teacher', 'POST', '/api/refires', {
    work_id: workId, source_batch_id: g.json.id, reason: '底足开裂，修坯后补烧',
  });
  assert.equal(r.status, 200);
  assert.equal(r.json.status, 'pending');
  const work = (await api(url, 'tok-teacher', 'GET', `/api/works/${workId}`)).json;
  assert.equal(work.status, 'refire_pending');
});

test('出窑清点：少件留痕 missing，全部清点完批次关闭', async (t) => {
  const app = await makeApp();
  t.after(() => app.server.close());
  const { service, clock, db, url } = app;
  const { batchId, workId } = makeFiringBatch(service, clock);
  clock.advanceHours(16);
  service.tick();
  await api(url, 'tok-teacher', 'POST', `/api/batches/${batchId}/open`);

  // 未开窑前不能清点（构造第二批验证状态机）
  const r = await api(url, 'tok-teacher', 'POST', `/api/batches/${batchId}/count`, {
    results: [{ work_id: workId, result: 'missing', note: '清点未找到' }],
  });
  assert.equal(r.status, 200);
  assert.equal(r.json.status, 'closed');
  assert.equal(eventsOf(db, 'missing').length, 1);
  const work = (await api(url, 'tok-teacher', 'GET', `/api/works/${workId}`)).json;
  assert.equal(work.status, 'missing');
});

test('照片：上传至本地目录并可访问', async (t) => {
  const app = await makeApp();
  t.after(() => app.server.close());
  const { service, clock, url } = app;
  const workId = makeDryWork(service, clock, {});
  const svg = '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>';
  const r = await api(url, 'tok-teacher', 'POST', '/api/photos', {
    owner_type: 'work', owner_id: workId, kind: 'product',
    filename: 'p.svg', data_base64: Buffer.from(svg).toString('base64'),
  });
  assert.equal(r.status, 200);
  const img = await fetch(url + r.json.path);
  assert.equal(img.status, 200);
  assert.match(img.headers.get('content-type'), /svg/);
});
