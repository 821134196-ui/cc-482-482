'use strict';

/**
 * 进程内任务：周期性推进批次状态机（firing→cooling→cooled）。
 * 干燥达标时点与完全冷却时点均在服务层登记/点火时计算落库，
 * 这里只负责到点迁移状态，便于测试用手动时钟直接调用 service.tick()。
 */
function startTicker(service, intervalMs = 30000) {
  const timer = setInterval(() => {
    try {
      service.tick();
    } catch (err) {
      console.error('[ticker] tick 失败:', err.message);
    }
  }, intervalMs);
  timer.unref();
  return timer;
}

module.exports = { startTicker };
