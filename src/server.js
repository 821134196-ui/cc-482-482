'use strict';

const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const { HttpError } = require('./util');
const { authenticate, requireUser, requireRole } = require('./auth');

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
};

const PHOTO_EXTS = new Set(['.svg', '.png', '.jpg', '.jpeg']);

/**
 * 组装 HTTP 服务：API 路由 + 前端静态目录 + 照片目录。
 * 依赖全部注入，测试可用内存库与临时目录构建。
 */
function createServer({ db, service, publicDir, photoDir }) {
  const routes = [];
  const route = (method, pattern, handler) => routes.push({ method, pattern, handler });

  const teacher = (req) => requireRole(req, 'teacher', 'admin');
  const admin = (req) => requireRole(req, 'admin');

  // ---------- 元数据与查询 ----------
  route('GET', '/api/meta', (req) => ({
    classes: db.prepare('SELECT * FROM classes ORDER BY id').all(),
    students: db.prepare(
      `SELECT s.id, s.code, s.class_id, c.name AS class_name FROM students s JOIN classes c ON c.id=s.class_id ORDER BY s.code`
    ).all(),
    clays: db.prepare('SELECT * FROM clays ORDER BY id').all(),
    glazes: db.prepare('SELECT * FROM glazes ORDER BY id').all(),
    glaze_conflicts: db.prepare(
      `SELECT gc.*, ga.name AS a_name, gb.name AS b_name FROM glaze_conflicts gc
       JOIN glazes ga ON ga.id=gc.glaze_a JOIN glazes gb ON gb.id=gc.glaze_b`
    ).all(),
    kilns: db.prepare('SELECT * FROM kilns ORDER BY id').all(),
    programs: db.prepare('SELECT * FROM programs ORDER BY id').all().map((p) => ({
      ...p, curve: require('./kilnSim').computeCurve(p),
    })),
    me: req.user ? { username: req.user.username, role: req.user.role, display_name: req.user.display_name } : null,
  }));

  route('GET', '/api/works', (req) => {
    requireUser(req);
    const status = req.query.status || null;
    return service.listWorks(status ? { status } : {});
  });

  route('GET', '/api/works/:id', (req) => {
    requireUser(req);
    return service.workDetail(Number(req.params.id));
  });

  route('GET', '/api/drying-queue', (req) => {
    requireUser(req);
    return service.dryingQueue();
  });

  route('GET', '/api/batches', (req) => {
    requireUser(req);
    return service.listBatches(req.query.from && req.query.to ? { from: req.query.from, to: req.query.to } : {});
  });

  route('GET', '/api/batches/:id', (req) => {
    requireUser(req);
    return service.batchDetail(Number(req.params.id));
  });

  route('GET', '/api/batches/:id/layout', (req) => {
    requireUser(req);
    return service.batchLayout(Number(req.params.id));
  });

  route('GET', '/api/cooling', (req) => {
    requireUser(req);
    return service.coolingList();
  });

  route('GET', '/api/refires', (req) => {
    requireUser(req);
    return service.refireList();
  });

  route('GET', '/api/events', (req) => {
    requireUser(req);
    return service.listEvents({
      entityType: req.query.entity_type,
      entityId: req.query.entity_id ? Number(req.query.entity_id) : undefined,
      anomaliesOnly: req.query.anomalies === '1',
    });
  });

  route('GET', '/api/kilns/:id/temperature', (req) => {
    requireUser(req);
    return service.kilnTemperature(Number(req.params.id));
  });

  route('GET', '/api/programs/:id/curve', (req) => {
    requireUser(req);
    const program = service.getProgram(Number(req.params.id));
    return { program, curve: require('./kilnSim').computeCurve(program) };
  });

  // 学生端：无需令牌，只读作品进度与成品照片
  route('GET', '/api/student/:code', (req) => service.studentView(req.params.code));

  // ---------- 作品与干燥（教师） ----------
  route('POST', '/api/works', (req) => {
    const actor = teacher(req);
    const b = req.body;
    return service.registerWork(actor, {
      studentCode: b.student_code, clayId: Number(b.clay_id),
      glazeId: b.glaze_id == null ? null : Number(b.glaze_id),
      widthMm: b.width_mm, depthMm: b.depth_mm, heightMm: b.height_mm,
    });
  });

  route('POST', '/api/works/:id/confirm-dry', (req) => {
    return service.confirmDry(teacher(req), Number(req.params.id));
  });

  route('POST', '/api/works/:id/label-lost', (req) => {
    return service.reportLabelLost(teacher(req), Number(req.params.id), req.body.note);
  });

  // ---------- 批次（教师排期；点火/停电仅管理员） ----------
  route('POST', '/api/batches', (req) => {
    const actor = teacher(req);
    const b = req.body;
    return service.createBatch(actor, {
      name: b.name, kilnId: Number(b.kiln_id), programId: Number(b.program_id),
      kind: b.kind, start: b.start, end: b.end,
    });
  });

  route('POST', '/api/batches/:id/items', (req) => {
    return service.addWorkToBatch(teacher(req), Number(req.params.id), Number(req.body.work_id));
  });

  route('DELETE', '/api/batches/:id/items/:workId', (req) => {
    return service.removeWorkFromBatch(teacher(req), Number(req.params.id), Number(req.params.workId));
  });

  route('POST', '/api/batches/:id/auto-assign', (req) => {
    return service.autoAssign(teacher(req), Number(req.params.id));
  });

  route('POST', '/api/batches/:id/items/:workId/position', (req) => {
    const b = req.body;
    return service.assignPosition(teacher(req), Number(req.params.id), Number(req.params.workId),
      Number(b.shelf_no), b.angle_deg != null ? Number(b.angle_deg) : null,
      b.radius_mm != null ? Number(b.radius_mm) : null);
  });

  route('POST', '/api/batches/:id/ignite', (req) => service.ignite(admin(req), Number(req.params.id)));
  route('POST', '/api/batches/:id/open', (req) => service.openBatch(requireUser(req), Number(req.params.id)));
  route('POST', '/api/batches/:id/cancel', (req) => service.cancelBatch(teacher(req), Number(req.params.id)));

  route('POST', '/api/batches/:id/count', (req) => {
    const results = (req.body.results || []).map((r) => ({
      workId: Number(r.work_id), result: r.result, note: r.note,
    }));
    return service.countBatch(teacher(req), Number(req.params.id), results);
  });

  route('POST', '/api/kilns/:id/power-outage', (req) => {
    return service.powerOutage(admin(req), Number(req.params.id), req.body.note);
  });

  route('POST', '/api/refires', (req) => {
    const b = req.body;
    return service.createRefire(teacher(req), {
      workId: Number(b.work_id), sourceBatchId: Number(b.source_batch_id), reason: b.reason,
    });
  });

  // ---------- 照片（本地目录存储） ----------
  route('POST', '/api/photos', (req) => {
    const actor = teacher(req);
    const b = req.body;
    if (!['batch', 'work'].includes(b.owner_type)) throw new HttpError(400, 'BAD_FIELD', 'owner_type 须为 batch 或 work');
    if (!['loading', 'product'].includes(b.kind)) throw new HttpError(400, 'BAD_FIELD', 'kind 须为 loading 或 product');
    const ext = path.extname(String(b.filename || '')).toLowerCase();
    if (!PHOTO_EXTS.has(ext)) throw new HttpError(400, 'BAD_FIELD', `仅支持 ${[...PHOTO_EXTS].join('/')}`);
    let buf;
    try {
      buf = Buffer.from(String(b.data_base64 || ''), 'base64');
    } catch {
      throw new HttpError(400, 'BAD_FIELD', 'data_base64 解码失败');
    }
    if (!buf.length || buf.length > 4 * 1024 * 1024) throw new HttpError(400, 'BAD_FIELD', '照片大小须为 1B~4MB');
    fs.mkdirSync(photoDir, { recursive: true });
    const fname = `${b.owner_type}-${b.owner_id}-${b.kind}-${Date.now()}${ext}`;
    fs.writeFileSync(path.join(photoDir, fname), buf);
    const relPath = `/photos/${fname}`;
    const info = db.prepare(
      'INSERT INTO photos (owner_type, owner_id, kind, path, uploaded_by, created_at) VALUES (?,?,?,?,?,?)'
    ).run(b.owner_type, Number(b.owner_id), b.kind, relPath, actor.username, service.now());
    service.recordEvent(b.owner_type, Number(b.owner_id), 'photo_uploaded',
      `${b.kind === 'loading' ? '装窑' : '成品'}照片 ${relPath}`, actor.username);
    return { id: Number(info.lastInsertRowid), path: relPath };
  });

  // ---------- 服务器 ----------
  const server = http.createServer(async (req, res) => {
    try {
      const url = new URL(req.url, 'http://localhost');
      req.query = Object.fromEntries(url.searchParams);
      req.user = authenticate(db, req);

      const pathname = url.pathname;
      for (const r of routes) {
        const params = matchPath(r.pattern, pathname);
        if (params && r.method === req.method) {
          req.params = params;
          if (['POST', 'PUT', 'PATCH'].includes(req.method)) req.body = await readJson(req);
          const result = await r.handler(req);
          return sendJson(res, 200, result);
        }
      }
      if (req.method === 'GET') return serveStatic(req, res, pathname, publicDir, photoDir);
      sendJson(res, 404, { error: 'NOT_FOUND', message: `${req.method} ${pathname} 不存在` });
    } catch (err) {
      if (err instanceof HttpError) {
        sendJson(res, err.status, { error: err.code, message: err.message });
      } else {
        console.error(err);
        sendJson(res, 500, { error: 'INTERNAL', message: '服务器内部错误' });
      }
    }
  });
  return server;
}

function matchPath(pattern, pathname) {
  const pSeg = pattern.split('/').filter(Boolean);
  const aSeg = pathname.split('/').filter(Boolean);
  if (pSeg.length !== aSeg.length) return null;
  const params = {};
  for (let i = 0; i < pSeg.length; i++) {
    if (pSeg[i].startsWith(':')) params[pSeg[i].slice(1)] = decodeURIComponent(aSeg[i]);
    else if (pSeg[i] !== aSeg[i]) return null;
  }
  return params;
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on('data', (c) => {
      size += c.length;
      if (size > 8 * 1024 * 1024) {
        reject(new HttpError(413, 'TOO_LARGE', '请求体过大'));
        req.destroy();
        return;
      }
      chunks.push(c);
    });
    req.on('end', () => {
      if (!chunks.length) return resolve({});
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString('utf8')));
      } catch {
        reject(new HttpError(400, 'BAD_JSON', '请求体不是合法 JSON'));
      }
    });
    req.on('error', reject);
  });
}

function sendJson(res, status, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(status, { 'content-type': 'application/json; charset=utf-8' });
  res.end(body);
}

function serveStatic(req, res, pathname, publicDir, photoDir) {
  let filePath;
  if (pathname.startsWith('/photos/')) {
    filePath = path.join(photoDir, path.normalize(pathname.slice('/photos/'.length)));
    if (!filePath.startsWith(path.resolve(photoDir))) return sendJson(res, 403, { error: 'FORBIDDEN' });
  } else {
    const rel = pathname === '/' ? 'index.html' : pathname.replace(/^\/+/, '');
    filePath = path.join(publicDir, path.normalize(rel));
    if (!filePath.startsWith(path.resolve(publicDir))) return sendJson(res, 403, { error: 'FORBIDDEN' });
  }
  fs.readFile(filePath, (err, data) => {
    if (err) return sendJson(res, 404, { error: 'NOT_FOUND', message: '文件不存在' });
    res.writeHead(200, { 'content-type': MIME[path.extname(filePath).toLowerCase()] || 'application/octet-stream' });
    res.end(data);
  });
}

module.exports = { createServer };
