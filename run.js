'use strict';

/**
 * 一条本地启动命令：node run.js
 * 初始化 SQLite → 载入样例（釉料相冲 / 停电中断 / 补烧）→ 启动服务。
 */
const fs = require('node:fs');
const path = require('node:path');
const { openDb } = require('./src/db');
const { KilnService } = require('./src/services');
const { realClock } = require('./src/clock');
const { createServer } = require('./src/server');
const { seedIfEmpty } = require('./src/seed');
const { startTicker } = require('./src/tasks');

const ROOT = __dirname;
const dataDir = path.join(ROOT, 'data');
const photoDir = path.join(ROOT, 'photos');
fs.mkdirSync(dataDir, { recursive: true });
fs.mkdirSync(photoDir, { recursive: true });

const db = openDb(path.join(dataDir, 'kiln.db'));
const service = new KilnService({ db, clock: realClock(), photoDir });

if (seedIfEmpty(db, photoDir)) {
  console.log('✔ 已载入样例数据（含釉料相冲、停电中断、补烧、开窑过早等留痕）');
}

startTicker(service, 30000); // 进程内任务：推进冷却状态机

const server = createServer({
  db,
  service,
  publicDir: path.join(ROOT, 'public'),
  photoDir,
});

const port = Number(process.env.PORT || 8080);
server.listen(port, () => {
  console.log(`陶艺教室窑炉排期系统已启动: http://localhost:${port}`);
  console.log('演示令牌 — 管理员: tok-admin  教师: tok-teacher  学生端: 输入代号如 S3-01');
});
