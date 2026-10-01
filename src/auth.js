'use strict';

const { HttpError } = require('./util');

/** 从 Authorization: Bearer <token> 解析用户；无令牌返回 null */
function authenticate(db, req) {
  const header = req.headers['authorization'] || '';
  const m = /^Bearer\s+(.+)$/.exec(header);
  if (!m) return null;
  const row = db.prepare(
    'SELECT u.id, u.username, u.display_name, u.role FROM tokens t JOIN users u ON u.id=t.user_id WHERE t.token=?'
  ).get(m[1]);
  return row || null;
}

function requireUser(req) {
  if (!req.user) throw new HttpError(401, 'UNAUTHENTICATED', '需要登录令牌');
  return req.user;
}

/** 权限边界：教师可排期与日常操作；点火、停电、异常开窑仅管理员 */
function requireRole(req, ...roles) {
  const user = requireUser(req);
  if (!roles.includes(user.role)) {
    throw new HttpError(403, 'FORBIDDEN', `需要 ${roles.join('/')} 权限，当前角色 ${user.role}`);
  }
  return user;
}

module.exports = { authenticate, requireUser, requireRole };
