'use strict';

/** 真实时钟（服务端使用） */
function realClock() {
  return { now: () => new Date().toISOString() };
}

/** 手动时钟（测试注入，可推进时间以驱动干燥/冷却时点） */
function manualClock(startIso) {
  let cur = new Date(startIso).getTime();
  return {
    now: () => new Date(cur).toISOString(),
    set: (isoStr) => { cur = new Date(isoStr).getTime(); },
    advanceHours: (h) => { cur += h * 3600 * 1000; },
  };
}

module.exports = { realClock, manualClock };
