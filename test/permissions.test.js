'use strict';

/** 权限边界：教师可排期；点火/停电/异常开窑仅管理员；学生端只读 */
const test = require('node:test');
const assert = require('node:assert/strict');
const { makeApp, api, h, makeDryWork, makeFiringBatch } = require('./helpers');

test('权限：未认证请求一律 401', async (t) => {
  const app = await makeApp();
  t.after(() => app.server.close());
  for (const [method, path] of [
    ['GET', '/api/works'], ['POST', '/api/works'], ['GET', '/api/batches'],
    ['POST', '/api/batches'], ['GET', '/api/cooling'], ['GET', '/api/events'],
  ]) {
    const r = await api(app.url, null, method, path, method === 'POST' ? {} : undefined);
    assert.equal(r.status, 401, `${method} ${path} 应 401`);
  }
  // 学生端查询无需令牌
  const s = await api(app.url, null, 'GET', '/api/student/S3-01');
  assert.equal(s.status, 200);
});

test('权限：教师可排期与日常操作，但不能点火/停电', async (t) => {
  const app = await makeApp();
  t.after(() => app.server.close());
  const { service, clock, url } = app;

  // 教师排期、登记、装窑均允许
  const workId = makeDryWork(service, clock, { student: 'S3-01' });
  const b = await api(url, 'tok-teacher', 'POST', '/api/batches', {
    name: '权限测试窑', kiln_id: 1, program_id: 1, kind: 'bisque',
    start: h(clock, 0), end: h(clock, 20),
  });
  assert.equal(b.status, 200);
  await api(url, 'tok-teacher', 'POST', `/api/batches/${b.json.id}/items`, { work_id: workId });
  const assign = await api(url, 'tok-teacher', 'POST', `/api/batches/${b.json.id}/auto-assign`);
  assert.equal(assign.status, 200);

  // 教师点火 → 403
  let r = await api(url, 'tok-teacher', 'POST', `/api/batches/${b.json.id}/ignite`);
  assert.equal(r.status, 403);
  assert.equal(r.json.error, 'FORBIDDEN');

  // 教师模拟停电 → 403
  r = await api(url, 'tok-teacher', 'POST', '/api/kilns/1/power-outage', { note: 'x' });
  assert.equal(r.status, 403);

  // 管理员点火 → 200，批次锁定
  r = await api(url, 'tok-admin', 'POST', `/api/batches/${b.json.id}/ignite`);
  assert.equal(r.status, 200);
  assert.equal(r.json.status, 'firing');

  // 锁定后教师不能再加作品
  const work2 = makeDryWork(service, clock, { student: 'S3-02' });
  r = await api(url, 'tok-teacher', 'POST', `/api/batches/${b.json.id}/items`, { work_id: work2 });
  assert.equal(r.status, 409);
  assert.equal(r.json.error, 'BATCH_LOCKED');

  // 管理员停电 → 200 并留痕
  r = await api(url, 'tok-admin', 'POST', '/api/kilns/1/power-outage', { note: '测试断电' });
  assert.equal(r.status, 200);
  assert.equal(r.json.status, 'interrupted');
});

test('权限：学生端只读，不暴露设备控制信息', async (t) => {
  const app = await makeApp();
  t.after(() => app.server.close());
  const { service, clock, url } = app;
  makeFiringBatch(service, clock); // 让学生作品处于在烧状态

  const r = await api(url, null, 'GET', '/api/student/S3-01');
  assert.equal(r.status, 200);
  const work = r.json.works[0];
  assert.ok(work.progress, '应包含进度');
  const keys = Object.keys(work);
  for (const forbidden of ['kiln_id', 'batch_id', 'ignited_at', 'cooled_until', 'shelf_no']) {
    assert.ok(!keys.includes(forbidden), `学生端不应暴露 ${forbidden}`);
  }
  // 学生令牌不存在：任何写操作对学生角色不可用（无令牌即 401）
  const w = await api(url, null, 'POST', '/api/works', { student_code: 'S3-01', clay_id: 1, width_mm: 1, depth_mm: 1, height_mm: 1 });
  assert.equal(w.status, 401);
});

test('权限：异常开窑仅管理员（教师 403）', async (t) => {
  const app = await makeApp();
  t.after(() => app.server.close());
  const { service, clock, url } = app;
  const { batchId } = makeFiringBatch(service, clock);
  clock.advanceHours(8); // 冷却中
  service.tick();
  const r = await api(url, 'tok-teacher', 'POST', `/api/batches/${batchId}/open`);
  assert.equal(r.status, 403);
  const r2 = await api(url, 'tok-admin', 'POST', `/api/batches/${batchId}/open`);
  assert.equal(r2.status, 200);
});
