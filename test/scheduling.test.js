'use strict';

/** 排期互斥：同一窑炉时段不能重叠 */
const test = require('node:test');
const assert = require('node:assert/strict');
const { makeApp, api, h } = require('./helpers');

test('排期互斥：同窑时段重叠被拒绝，相邻与异窑允许', async (t) => {
  const app = await makeApp();
  t.after(() => app.server.close());
  const { url, clock } = app;
  const T = 'tok-teacher';

  const mk = (kilnId, startH, endH, name) => api(url, T, 'POST', '/api/batches', {
    name, kiln_id: kilnId, program_id: 1, kind: 'bisque',
    start: h(clock, startH), end: h(clock, endH),
  });

  let r = await mk(1, 10, 20, '基础批次');
  assert.equal(r.status, 200, '首个批次应排期成功');
  const baseId = r.json.id;

  r = await mk(1, 15, 25, '尾部重叠');
  assert.equal(r.status, 409);
  assert.equal(r.json.error, 'SCHEDULE_OVERLAP');

  r = await mk(1, 5, 11, '头部重叠');
  assert.equal(r.status, 409);

  r = await mk(1, 12, 14, '包含重叠');
  assert.equal(r.status, 409);

  r = await mk(1, 20, 30, '首尾相接');
  assert.equal(r.status, 200, '结束=开始 的相邻排期应允许');

  r = await mk(1, 0, 10, '前邻接');
  assert.equal(r.status, 200);

  r = await mk(2, 15, 25, '另一窑炉同时段');
  assert.equal(r.status, 200, '不同窑炉时段互不影响');

  // 取消后时段释放
  r = await api(url, T, 'POST', `/api/batches/${baseId}/cancel`);
  assert.equal(r.status, 200);
  r = await mk(1, 11, 19, '取消后重排');
  assert.equal(r.status, 200, '已取消批次不再占用时段');
});

test('排期校验：程序类型与批次类型必须匹配', async (t) => {
  const app = await makeApp();
  t.after(() => app.server.close());
  const r = await api(app.url, 'tok-teacher', 'POST', '/api/batches', {
    name: '错配', kiln_id: 1, program_id: 2, kind: 'bisque',
    start: h(app.clock, 0), end: h(app.clock, 10),
  });
  assert.equal(r.status, 409);
  assert.equal(r.json.error, 'PROGRAM_KIND_MISMATCH');
});
