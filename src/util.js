'use strict';

/** 业务错误：携带 HTTP 状态码与机器可读错误码 */
class HttpError extends Error {
  constructor(status, code, message) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

const HOUR_MS = 3600 * 1000;

function iso(date) {
  return new Date(date).toISOString();
}

function addHours(isoStr, hours) {
  return new Date(new Date(isoStr).getTime() + hours * HOUR_MS).toISOString();
}

function hoursBetween(fromIso, toIso) {
  return (new Date(toIso).getTime() - new Date(fromIso).getTime()) / HOUR_MS;
}

/** 校验并返回有限正数，否则抛 400 */
function requireNumber(value, field, { min = 0, max = Number.MAX_SAFE_INTEGER } = {}) {
  const n = Number(value);
  if (!Number.isFinite(n) || n < min || n > max) {
    throw new HttpError(400, 'BAD_FIELD', `字段 ${field} 必须是 ${min}~${max} 之间的数字`);
  }
  return n;
}

function requireString(value, field, { maxLen = 500 } = {}) {
  if (typeof value !== 'string' || value.trim() === '' || value.length > maxLen) {
    throw new HttpError(400, 'BAD_FIELD', `字段 ${field} 不能为空且不超过 ${maxLen} 字`);
  }
  return value.trim();
}

function requireIso(value, field) {
  const t = new Date(value);
  if (typeof value !== 'string' || Number.isNaN(t.getTime())) {
    throw new HttpError(400, 'BAD_FIELD', `字段 ${field} 必须是 ISO 时间字符串`);
  }
  return t.toISOString();
}

module.exports = { HttpError, HOUR_MS, iso, addHours, hoursBetween, requireNumber, requireString, requireIso };
