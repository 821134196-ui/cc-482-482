'use strict';

/**
 * 窑温模拟适配器：根据烧制程序曲线与点火时间推算当前窑温。
 * 真实部署时替换为热电偶读取即可，接口保持不变。
 */

const AMBIENT_C = 25;          // 室温
const OUTAGE_COOL_RATE = 150;  // 停电后自然降温 °C/h

/**
 * 把程序步骤展开为阶梯曲线关键点 [{t: 小时, temp: °C}]。
 * 每步 = 升温段 + 保温段；末尾追加自然冷却段到室温。
 */
function computeCurve(program) {
  const steps = JSON.parse(program.steps_json);
  const points = [{ t: 0, temp: AMBIENT_C }];
  let t = 0;
  let temp = AMBIENT_C;
  for (const s of steps) {
    const rampHours = Math.abs(s.target - temp) / s.ramp;
    t += rampHours;
    temp = s.target;
    points.push({ t, temp });
    if (s.hold > 0) {
      t += s.hold / 60;
      points.push({ t, temp });
    }
  }
  const firingHours = t;
  const peak = Math.max(...points.map((p) => p.temp));
  const coolingHours = (peak - AMBIENT_C) / program.cool_rate_c_per_h;
  points.push({ t: firingHours + coolingHours, temp: AMBIENT_C });
  return { points, firingHours, coolingHours, peak };
}

/** 曲线上 elapsedHours 时刻的温度（ firing 段，线性插值） */
function tempOnCurve(points, elapsedHours) {
  if (elapsedHours <= 0) return points[0].temp;
  for (let i = 1; i < points.length; i++) {
    const a = points[i - 1];
    const b = points[i];
    if (elapsedHours <= b.t) {
      if (b.t === a.t) return b.temp;
      const k = (elapsedHours - a.t) / (b.t - a.t);
      return a.temp + k * (b.temp - a.temp);
    }
  }
  return points[points.length - 1].temp;
}

/** 确定性小噪声，避免读数完全平直 */
function noise(elapsedHours) {
  return Math.sin(elapsedHours * 7.13) * 2;
}

/**
 * 读取窑当前温度。
 * @param program  程序行
 * @param ignitedAt 点火时间 ISO
 * @param nowIso    当前时间 ISO
 * @param interruptedAt 停电中断时间 ISO（可选）
 */
function readTemperature(program, ignitedAt, nowIso, interruptedAt = null) {
  const { points, firingHours } = computeCurve(program);
  const elapsed = (new Date(nowIso) - new Date(ignitedAt)) / 3600000;
  if (elapsed < 0) return { temp_c: AMBIENT_C, phase: 'standby', elapsed_h: 0 };

  if (interruptedAt) {
    const atInterrupt = (new Date(interruptedAt) - new Date(ignitedAt)) / 3600000;
    const tempThen = tempOnCurve(points, Math.min(atInterrupt, firingHours));
    const sinceInterrupt = elapsed - atInterrupt;
    const temp = Math.max(AMBIENT_C, tempThen - OUTAGE_COOL_RATE * sinceInterrupt);
    return { temp_c: Math.round(temp * 10) / 10, phase: 'interrupted', elapsed_h: round1(elapsed) };
  }

  if (elapsed <= firingHours) {
    return {
      temp_c: round1(tempOnCurve(points, elapsed) + noise(elapsed)),
      phase: 'firing',
      elapsed_h: round1(elapsed),
    };
  }
  const coolingElapsed = elapsed - firingHours;
  const temp = tempOnCurve(points, elapsed);
  return {
    temp_c: round1(Math.max(AMBIENT_C, temp) + noise(coolingElapsed) * 0.5),
    phase: temp <= AMBIENT_C + 1 ? 'cooled' : 'cooling',
    elapsed_h: round1(elapsed),
  };
}

function round1(n) {
  return Math.round(n * 10) / 10;
}

module.exports = { computeCurve, readTemperature, tempOnCurve, AMBIENT_C };
