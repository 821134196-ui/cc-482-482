'use strict';

/* ================= 基础 ================= */

const TOKENS = { admin: 'tok-admin', teacher: 'tok-teacher' };
const state = {
  role: localStorage.getItem('role') || 'teacher',
  meta: null,
  selectedBatch: Number(localStorage.getItem('batch')) || null,
  studentCode: localStorage.getItem('studentCode') || 'S3-01',
};

function token() { return TOKENS[state.role] || null; }

async function api(method, path, body) {
  const headers = {};
  const t = token();
  if (t) headers['authorization'] = `Bearer ${t}`;
  if (body !== undefined) headers['content-type'] = 'application/json';
  const res = await fetch(path, { method, headers, body: body !== undefined ? JSON.stringify(body) : undefined });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const err = new Error(data.message || `请求失败 ${res.status}`);
    err.code = data.error;
    err.status = res.status;
    throw err;
  }
  return data;
}

function toast(msg, kind = '') {
  const box = document.getElementById('toasts');
  const el = document.createElement('div');
  el.className = `toast ${kind}`;
  el.textContent = msg;
  box.appendChild(el);
  setTimeout(() => el.remove(), 4200);
}
const ok = (m) => toast(m, 'ok');
const err = (e) => toast(e.message || String(e), 'err');

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function fmtT(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, '0');
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

/* ================= 字典 ================= */

const WORK_STATUS = {
  drying: ['干燥中', ''], dry_qualified: ['干燥合格', 'ok'], scheduled: ['已排入批次', ''],
  firing: ['烧制中', 'hot'], cooling: ['冷却中', ''], awaiting_glaze: ['待釉烧', ''],
  finished: ['已完成', 'ok'], damaged: ['裂损', 'bad'], missing: ['少件', 'bad'],
  refire_pending: ['待补烧', 'hot'],
};
const BATCH_STATUS = {
  scheduled: ['已排期', ''], loaded: ['已装窑', ''], firing: ['烧制中', 'hot'],
  cooling: ['冷却中', ''], cooled: ['已冷却·可开窑', 'ok'], opened: ['已开窑', ''],
  closed: ['已清点', 'muted'], interrupted: ['停电中断', 'bad'], cancelled: ['已取消', 'muted'],
};
const EVENT_LABEL = {
  label_lost: '标签脱落', dry_insufficient: '干燥不足', glaze_conflict: '釉料相冲',
  over_height: '装载超高', power_outage: '停电中断', early_open: '开窑过早',
  cracked: '裂损', missing: '作品少件',
  work_registered: '作品登记', dry_confirmed: '干燥合格', batch_created: '批次排期',
  work_scheduled: '作品入批', work_removed: '移出批次', loaded: '装窑完成',
  ignited: '点火锁定', cooling_started: '烧成结束', cooled: '完全冷却',
  opened: '开窑', counted: '清点完成', bisque_done: '素烧完好', finished: '作品完成',
  refire_created: '补烧单', photo_uploaded: '照片', batch_cancelled: '批次取消',
};
const ANOMALIES = new Set(['label_lost', 'dry_insufficient', 'glaze_conflict', 'over_height', 'power_outage', 'early_open', 'cracked', 'missing']);
const SEVERE = new Set(['power_outage', 'early_open', 'cracked', 'missing']);

function workChip(s) { const [t, c] = WORK_STATUS[s] || [s, '']; return `<span class="chip ${c}">${t}</span>`; }
function batchChip(s) { const [t, c] = BATCH_STATUS[s] || [s, '']; return `<span class="chip ${c}">${t}</span>`; }
function eventBadge(type) {
  const cls = SEVERE.has(type) ? 'severe' : ANOMALIES.has(type) ? 'anomaly' : '';
  return `<span class="event-badge ${cls}">${EVENT_LABEL[type] || type}</span>`;
}
const KIND_LABEL = { bisque: '素烧', glaze: '釉烧' };

/* ================= 路由 ================= */

const TABS = [
  ['works', '作品登记'], ['drying', '干燥队列'], ['calendar', '窑炉日历'],
  ['shelves', '棚板排布'], ['program', '程序确认'], ['cooling', '冷却计时'],
  ['counting', '出窑清点'], ['refires', '补烧追踪'], ['events', '留痕记录'],
];

function currentRoute() {
  const h = location.hash.replace(/^#\/?/, '');
  return h || (state.role === 'student' ? 'student' : 'works');
}

function renderTabs() {
  const nav = document.getElementById('tabs');
  if (state.role === 'student') {
    nav.innerHTML = `<a href="#/student" class="active">学生作品查询</a>`;
    return;
  }
  const r = currentRoute();
  nav.innerHTML = TABS.map(([k, label]) =>
    `<a href="#/${k}" class="${r === k ? 'active' : ''}">${label}</a>`).join('');
}

async function render() {
  document.querySelectorAll('.role-switch button').forEach((b) =>
    b.classList.toggle('active', b.dataset.role === state.role));
  renderTabs();
  const main = document.getElementById('main');
  const route = currentRoute();
  try {
    if (route === 'student' || state.role === 'student') return await renderStudent(main);
    if (!state.meta) state.meta = await api('GET', '/api/meta');
    const fn = {
      works: renderWorks, drying: renderDrying, calendar: renderCalendar,
      shelves: renderShelves, program: renderProgram, cooling: renderCooling,
      counting: renderCounting, refires: renderRefires, events: renderEvents,
    }[route] || renderWorks;
    await fn(main);
  } catch (e) {
    main.innerHTML = `<div class="panel"><h2>出错了</h2><p class="warn-text">${esc(e.message)}</p></div>`;
  }
}

document.querySelectorAll('.role-switch button').forEach((b) =>
  b.addEventListener('click', () => {
    state.role = b.dataset.role;
    localStorage.setItem('role', state.role);
    location.hash = state.role === 'student' ? '#/student' : '#/works';
    render();
  }));
window.addEventListener('hashchange', render);

/* ================= 作品登记 ================= */

async function renderWorks(main) {
  const m = state.meta;
  const works = await api('GET', '/api/works');
  main.innerHTML = `
  <div class="panel">
    <h2>作品登记 <span class="en">完成后自动进入自然干燥</span></h2>
    <form id="f-work">
      <label class="field">学生代号
        <select name="student_code">${m.students.map((s) => `<option value="${s.code}">${s.code}（${s.class_name}）</option>`).join('')}</select>
      </label>
      <label class="field">泥料
        <select name="clay_id">${m.clays.map((c) => `<option value="${c.id}">${c.name}（基干 ${c.dry_hours_base}h）</option>`).join('')}</select>
      </label>
      <label class="field">釉色（釉烧前选）
        <select name="glaze_id"><option value="">暂未施釉</option>${m.glazes.map((g) => `<option value="${g.id}">${g.name}</option>`).join('')}</select>
      </label>
      <label class="field">宽 mm<input name="width_mm" type="number" value="120" min="10" max="800" required></label>
      <label class="field">深 mm<input name="depth_mm" type="number" value="120" min="10" max="800" required></label>
      <label class="field">高 mm<input name="height_mm" type="number" value="150" min="10" max="800" required></label>
      <button>登记并进入干燥</button>
    </form>
  </div>
  <div class="panel">
    <h2>全部作品 <span class="en">共 ${works.length} 件 · 学生身份均为匿名代号</span></h2>
    <table><thead><tr>
      <th>代号</th><th>学生</th><th>泥料</th><th>釉色</th><th>尺寸(mm)</th><th>阶段</th><th>状态</th><th>操作</th>
    </tr></thead><tbody>
      ${works.map((w) => `<tr>
        <td><b>${w.code}</b></td><td>${w.student_code}</td><td>${w.clay_name}</td>
        <td>${w.glaze_name || '—'}</td><td>${w.width_mm}×${w.depth_mm}×${w.height_mm}</td>
        <td>${{ bisque: '素烧阶段', glaze: '釉烧阶段', done: '已完结' }[w.stage]}</td>
        <td>${workChip(w.status)}</td>
        <td>
          ${w.status === 'drying' && w.dry_ready ? `<button class="small" data-act="dry" data-id="${w.id}">确认干燥</button>` : ''}
          ${w.status === 'drying' && !w.dry_ready ? `<button class="small ghost" data-act="dry" data-id="${w.id}">尝试确认</button>` : ''}
          <button class="small ghost" data-act="label" data-id="${w.id}">标签脱落</button>
        </td>
      </tr>`).join('')}
    </tbody></table>
  </div>`;

  main.querySelector('#f-work').addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    try {
      const w = await api('POST', '/api/works', {
        student_code: f.student_code, clay_id: Number(f.clay_id),
        glaze_id: f.glaze_id ? Number(f.glaze_id) : null,
        width_mm: Number(f.width_mm), depth_mm: Number(f.depth_mm), height_mm: Number(f.height_mm),
      });
      ok(`已登记 ${w.code}，需自然干燥 ${w.dry_required_hours} 小时`);
      render();
    } catch (e2) { err(e2); }
  });
  main.querySelectorAll('[data-act]').forEach((b) => b.addEventListener('click', async () => {
    try {
      if (b.dataset.act === 'dry') {
        const w = await api('POST', `/api/works/${b.dataset.id}/confirm-dry`);
        ok(`${w.code} 干燥合格，可排入素烧`);
      } else {
        const note = prompt('标签脱落情况说明：', '搬运时碰落，已补贴');
        if (note == null) return;
        await api('POST', `/api/works/${b.dataset.id}/label-lost`, { note });
        ok('已留痕：标签脱落');
      }
      render();
    } catch (e2) { err(e2); }
  }));
}

/* ================= 干燥队列 ================= */

async function renderDrying(main) {
  const queue = await api('GET', '/api/drying-queue');
  main.innerHTML = `
  <div class="panel">
    <h2>干燥队列 <span class="en">干燥达标时点由系统按泥料与尺寸计算；未达标确认将被拒绝并留痕</span></h2>
    ${queue.length === 0 ? '<p class="muted">当前没有干燥中的作品。</p>' : `
    <table><thead><tr>
      <th>代号</th><th>学生</th><th>泥料</th><th>尺寸(mm)</th><th>要求时长</th><th>进度</th><th>达标时点</th><th>操作</th>
    </tr></thead><tbody>
      ${queue.map((w) => `<tr>
        <td><b>${w.code}</b></td><td>${w.student_code}</td><td>${w.clay_name}</td>
        <td>${w.width_mm}×${w.depth_mm}×${w.height_mm}</td><td>${w.dry_required_hours}h</td>
        <td><div class="progress"><i style="width:${Math.round(w.progress * 100)}%"></i></div></td>
        <td>${w.dry_ready ? '<span class="chip ok">已达标</span>' : `<span data-cd="${w.dry_due_at}">${fmtT(w.dry_due_at)}</span>`}</td>
        <td><button class="small ${w.dry_ready ? '' : 'ghost'}" data-id="${w.id}">确认干燥合格</button></td>
      </tr>`).join('')}
    </tbody></table>`}
  </div>`;
  main.querySelectorAll('button[data-id]').forEach((b) => b.addEventListener('click', async () => {
    try {
      const w = await api('POST', `/api/works/${b.dataset.id}/confirm-dry`);
      ok(`${w.code} 干燥合格`);
    } catch (e) { err(e); }
    render();
  }));
}

/* ================= 窑炉日历 ================= */

async function renderCalendar(main) {
  const m = state.meta;
  const now = Date.now();
  const from = new Date(now - 2 * 86400e3).toISOString();
  const to = new Date(now + 7 * 86400e3).toISOString();
  const batches = await api('GET', `/api/batches?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`);
  const span = new Date(to) - new Date(from);
  const pos = (iso) => Math.max(0, Math.min(100, ((new Date(iso) - new Date(from)) / span) * 100));

  main.innerHTML = `
  <div class="panel">
    <h2>窑炉日历 <span class="en">同一窑炉时段不可重叠 · 点击色块查看棚板排布</span></h2>
    <div class="legend">
      <span><i style="background:var(--kiln-orange)"></i>素烧</span>
      <span><i style="background:var(--glaze-blue)"></i>釉烧/冷却</span>
      <span><i style="background:var(--danger)"></i>中断</span>
      <span><i style="background:#9b8d76"></i>已结束</span>
    </div>
    <div class="calendar">
      ${m.kilns.map((k) => `
        <div class="cal-row">
          <div class="cal-kiln">${esc(k.name)}</div>
          <div class="cal-track">
            ${batches.filter((b) => b.kiln_id === k.id).map((b) => `
              <div class="cal-block ${b.kind} ${b.status}" data-batch="${b.id}"
                   style="left:${pos(b.scheduled_start)}%;width:${Math.max(3, pos(b.scheduled_end) - pos(b.scheduled_start))}%"
                   title="${esc(b.name)} ${fmtT(b.scheduled_start)}~${fmtT(b.scheduled_end)}">
                ${esc(b.name)} ${b.item_count}件
              </div>`).join('')}
          </div>
        </div>`).join('')}
    </div>
  </div>
  <div class="panel">
    <h2>新增排期 <span class="en">教师权限</span></h2>
    <form id="f-batch">
      <label class="field">批次名<input name="name" value="第${batches.length + 9}窑" required></label>
      <label class="field">窑炉
        <select name="kiln_id">${m.kilns.map((k) => `<option value="${k.id}">${k.name}</option>`).join('')}</select>
      </label>
      <label class="field">类型
        <select name="kind"><option value="bisque">素烧</option><option value="glaze">釉烧</option></select>
      </label>
      <label class="field">程序
        <select name="program_id">${m.programs.map((p) => `<option value="${p.id}">${p.name}</option>`).join('')}</select>
      </label>
      <label class="field">开始<input name="start" type="datetime-local" required></label>
      <label class="field">结束<input name="end" type="datetime-local" required></label>
      <button>排期</button>
    </form>
    <p class="muted" id="batch-list"></p>
  </div>`;

  const kindSel = main.querySelector('[name=kind]');
  const progSel = main.querySelector('[name=program_id]');
  const syncProg = () => {
    const kind = kindSel.value;
    progSel.innerHTML = m.programs.filter((p) => p.kind === kind)
      .map((p) => `<option value="${p.id}">${p.name}</option>`).join('');
  };
  kindSel.addEventListener('change', syncProg);
  syncProg();

  main.querySelectorAll('.cal-block').forEach((el) => el.addEventListener('click', () => {
    state.selectedBatch = Number(el.dataset.batch);
    localStorage.setItem('batch', state.selectedBatch);
    location.hash = '#/shelves';
  }));

  main.querySelector('#f-batch').addEventListener('submit', async (e) => {
    e.preventDefault();
    const f = Object.fromEntries(new FormData(e.target));
    try {
      const b = await api('POST', '/api/batches', {
        name: f.name, kiln_id: Number(f.kiln_id), program_id: Number(f.program_id),
        kind: f.kind,
        start: new Date(f.start).toISOString(), end: new Date(f.end).toISOString(),
      });
      ok(`批次「${b.name}」排期成功`);
      render();
    } catch (e2) { err(e2); }
  });
}

/* ================= 棚板排布（圆形俯视） ================= */

async function batchOptions() {
  const batches = await api('GET', '/api/batches');
  return batches.filter((b) => !['cancelled'].includes(b.status));
}

async function renderShelves(main) {
  const batches = await batchOptions();
  if (!state.selectedBatch || !batches.find((b) => b.id === state.selectedBatch)) {
    state.selectedBatch = batches[batches.length - 1]?.id || null;
  }
  if (!state.selectedBatch) {
    main.innerHTML = `<div class="panel"><h2>棚板排布</h2><p class="muted">暂无批次，请先在窑炉日历中排期。</p></div>`;
    return;
  }
  const [layout, detail] = await Promise.all([
    api('GET', `/api/batches/${state.selectedBatch}/layout`),
    api('GET', `/api/batches/${state.selectedBatch}`),
  ]);
  const editable = ['scheduled', 'loaded'].includes(detail.status);
  const eligible = (await api('GET', '/api/works')).filter((w) =>
    detail.kind === 'bisque'
      ? ['dry_qualified', 'refire_pending'].includes(w.status) && w.stage === 'bisque'
      : (['awaiting_glaze', 'refire_pending'].includes(w.status) && w.stage === 'glaze'));

  main.innerHTML = `
  <div class="panel">
    <h2>棚板排布 <span class="en">圆形棚板俯视 · 作品按编号与尺寸小块表示</span></h2>
    <div class="flex">
      <label class="field">批次
        <select id="sel-batch">${batches.map((b) =>
          `<option value="${b.id}" ${b.id === state.selectedBatch ? 'selected' : ''}>${esc(b.name)}（${KIND_LABEL[b.kind]}·${esc(b.kiln_name)}）</option>`).join('')}</select>
      </label>
      ${batchChip(detail.status)}
      <span class="muted">层间净高 ${detail.kiln.shelf_gap_mm}mm · 每层至多 ${detail.kiln.shelf_slot_capacity} 件</span>
      ${editable ? `<button id="btn-auto" class="blue">自动排布</button>` : '<span class="chip hot">已点火锁定</span>'}
      ${editable && detail.status !== 'cancelled' ? `<button id="btn-cancel" class="ghost">取消批次</button>` : ''}
    </div>
    ${editable ? `
    <form id="f-add" class="flex mt8">
      <label class="field">加入作品
        <select name="work_id">${eligible.map((w) =>
          `<option value="${w.id}">${w.code}（${w.student_code} · ${w.width_mm}×${w.depth_mm}×${w.height_mm}mm ${w.glaze_name || '未施釉'}）</option>`).join('')}</select>
      </label>
      <button ${eligible.length ? '' : 'disabled'}>加入批次</button>
      ${detail.kind === 'glaze' ? `<span class="muted">相冲釉色：${state.meta.glaze_conflicts.map((c) => `${c.a_name}×${c.b_name}`).join('、')}</span>` : ''}
    </form>` : ''}
  </div>
  <div class="panel">
    <div class="shelf-wrap" id="shelves"></div>
    ${layout.unplaced.length ? `<h3>未定位作品</h3><div class="flex">${layout.unplaced.map((it) =>
      `<span class="chip hot">${it.work_code}</span>`).join('')}</div>` : ''}
    <h3>批次作品（${detail.items.length}）</h3>
    <table><thead><tr><th>代号</th><th>学生</th><th>尺寸(mm)</th><th>釉色</th><th>层位</th><th>结果</th>${editable ? '<th>操作</th>' : ''}</tr></thead>
    <tbody>${detail.items.map((it) => `<tr>
      <td><b>${it.work_code}</b></td><td>${it.student_code}</td>
      <td>${it.width_mm}×${it.depth_mm}×${it.height_mm}</td><td>${it.glaze_name || '—'}</td>
      <td>${it.shelf_no ? `第 ${it.shelf_no} 层` : '<span class="warn-text">未定位</span>'}</td>
      <td>${{ pending: '—', intact: '<span class="chip ok">完好</span>', cracked: '<span class="chip bad">裂损</span>', missing: '<span class="chip bad">少件</span>' }[it.result]}</td>
      ${editable ? `<td>
        ${detail.kiln.shelf_count > 1 ? `<select data-move="${it.work_id}">
          <option value="">移到层…</option>
          ${Array.from({ length: detail.kiln.shelf_count }, (_, i) => `<option value="${i + 1}">第 ${i + 1} 层</option>`).join('')}
        </select>` : ''}
        <button class="small ghost" data-rm="${it.work_id}">移出</button>
      </td>` : ''}
    </tr>`).join('')}</tbody></table>
    <h3>装窑照片</h3>
    <div class="photo-grid">${detail.photos.filter((p) => p.kind === 'loading').map((p) => `<img src="${p.path}" alt="装窑照片">`).join('') || '<span class="muted">暂无</span>'}</div>
    ${editable ? `<div class="mt8"><input type="file" id="f-photo" accept=".svg,.png,.jpg,.jpeg"> <button class="small" id="btn-photo">上传装窑照片</button></div>` : ''}
    <h3>批次留痕</h3>
    ${eventList(detail.events)}
  </div>`;

  const wrap = main.querySelector('#shelves');
  wrap.innerHTML = layout.shelves.map((s) => shelfSvg(s, layout.kiln, detail)).join('');

  main.querySelector('#sel-batch').addEventListener('change', (e) => {
    state.selectedBatch = Number(e.target.value);
    localStorage.setItem('batch', state.selectedBatch);
    render();
  });
  const on = (id, fn) => { const el = main.querySelector(id); if (el) el.addEventListener('click', fn); };
  on('#btn-auto', async () => {
    try { await api('POST', `/api/batches/${state.selectedBatch}/auto-assign`); ok('自动排布完成'); }
    catch (e) { err(e); }
    render();
  });
  on('#btn-cancel', async () => {
    if (!confirm('确定取消该批次？作品将被释放。')) return;
    try { await api('POST', `/api/batches/${state.selectedBatch}/cancel`); ok('批次已取消'); }
    catch (e) { err(e); }
    render();
  });
  on('#btn-photo', async () => {
    const file = main.querySelector('#f-photo').files[0];
    if (!file) return toast('请先选择照片文件', 'err');
    try {
      await uploadPhoto('batch', state.selectedBatch, 'loading', file);
      ok('装窑照片已上传');
      render();
    } catch (e) { err(e); }
  });
  const fAdd = main.querySelector('#f-add');
  if (fAdd) fAdd.addEventListener('submit', async (e) => {
    e.preventDefault();
    const wid = Number(new FormData(fAdd).get('work_id'));
    try { await api('POST', `/api/batches/${state.selectedBatch}/items`, { work_id: wid }); ok('已加入批次'); }
    catch (e2) { err(e2); }
    render();
  });
  main.querySelectorAll('[data-rm]').forEach((b) => b.addEventListener('click', async () => {
    try { await api('DELETE', `/api/batches/${state.selectedBatch}/items/${b.dataset.rm}`); ok('已移出'); }
    catch (e) { err(e); }
    render();
  }));
  main.querySelectorAll('[data-move]').forEach((sel) => sel.addEventListener('change', async () => {
    if (!sel.value) return;
    try {
      await api('POST', `/api/batches/${state.selectedBatch}/items/${sel.dataset.move}/position`, { shelf_no: Number(sel.value) });
      ok('已调整层位');
    } catch (e) { err(e); }
    render();
  }));
}

/** 圆形棚板俯视 SVG：作品为编号+尺寸小块 */
function shelfSvg(shelf, kiln, detail) {
  const R = 90;
  const scale = R / shelf.radius_mm;
  const cx = 100, cy = 100;
  const blocks = shelf.items.map((it) => {
    const a = ((it.slot_angle_deg || 0) - 90) * Math.PI / 180;
    const r = (it.slot_radius_mm || 0) * scale;
    const x = cx + Math.cos(a) * r;
    const y = cy + Math.sin(a) * r;
    const w = Math.max(14, it.width_mm * scale);
    const h = Math.max(14, it.depth_mm * scale);
    const color = it.result === 'cracked' ? '#b3402a'
      : it.result === 'missing' ? '#8a7a66'
      : it.result === 'intact' ? '#4d7c4d'
      : it.glaze_color || '#2f6f8f';
    return `<g transform="rotate(${it.slot_angle_deg || 0} ${x} ${y})">
      <rect x="${x - w / 2}" y="${y - h / 2}" width="${w}" height="${h}" rx="3"
            fill="${color}" opacity="0.9" stroke="#fff" stroke-width="1">
        <title>${it.work_code} ${it.width_mm}×${it.depth_mm}×${it.height_mm}mm ${it.glaze_name || ''}</title>
      </rect>
      <text x="${x}" y="${y + 2.5}" text-anchor="middle" font-size="6.5" fill="#fff" pointer-events="none">${it.work_code.replace('W-0', '')}</text>
    </g>`;
  }).join('');
  return `<div class="shelf-card">
    <svg class="shelf-svg" width="200" height="200" viewBox="0 0 200 200">
      <circle cx="${cx}" cy="${cy}" r="${R}" fill="#f3ecdf" stroke="#c9b99a" stroke-width="2"/>
      <circle cx="${cx}" cy="${cy}" r="${R * 0.45}" fill="none" stroke="#e0d4bd" stroke-dasharray="3 4"/>
      <circle cx="${cx}" cy="${cy}" r="${R * 0.8}" fill="none" stroke="#e0d4bd" stroke-dasharray="3 4"/>
      ${blocks}
    </svg>
    <h4>第 ${shelf.shelf_no} 层 · ${shelf.items.length} 件</h4>
  </div>`;
}

/* ================= 程序确认（阶梯曲线 + 点火） ================= */

async function renderProgram(main) {
  const batches = await batchOptions();
  if (!state.selectedBatch || !batches.find((b) => b.id === state.selectedBatch)) {
    state.selectedBatch = batches[batches.length - 1]?.id || null;
  }
  if (!state.selectedBatch) {
    main.innerHTML = `<div class="panel"><h2>程序确认</h2><p class="muted">暂无批次。</p></div>`;
    return;
  }
  const detail = await api('GET', `/api/batches/${state.selectedBatch}`);
  const curve = detail.program.curve;
  let tempInfo = null;
  if (['firing', 'cooling', 'interrupted'].includes(detail.status)) {
    tempInfo = await api('GET', `/api/kilns/${detail.kiln_id}/temperature`);
  }

  main.innerHTML = `
  <div class="panel">
    <h2>程序确认 <span class="en">点火后批次与程序锁定 · 点火仅管理员</span></h2>
    <div class="flex">
      <label class="field">批次
        <select id="sel-batch">${batches.map((b) =>
          `<option value="${b.id}" ${b.id === state.selectedBatch ? 'selected' : ''}>${esc(b.name)}（${KIND_LABEL[b.kind]}）</option>`).join('')}</select>
      </label>
      ${batchChip(detail.status)}
    </div>
    <div class="kv">
      <span>程序：<b>${esc(detail.program_name)}</b></span>
      <span>峰值温度：<b>${curve.peak}°C</b></span>
      <span>烧成约：<b>${curve.firingHours.toFixed(1)}h</b></span>
      <span>冷却约：<b>${curve.coolingHours.toFixed(1)}h</b></span>
      ${detail.ignited_at ? `<span>点火：<b>${fmtT(detail.ignited_at)}</b>（${esc(detail.ignited_by || '')}）</span>` : ''}
      ${detail.cooled_until ? `<span>完全冷却：<b>${fmtT(detail.cooled_until)}</b></span>` : ''}
    </div>
    ${curveSvg(curve, tempInfo)}
    <div class="flex mt8">
      ${tempInfo ? `<span class="chip hot">当前窑温 ${tempInfo.temp_c}°C（${tempInfo.phase}）</span>` : ''}
      ${detail.status === 'loaded' || detail.status === 'interrupted'
        ? `<button id="btn-ignite">🔥 确认程序并点火（管理员）</button>
           <span class="muted">点火后不能再增删作品或更换程序</span>`
        : detail.status === 'firing' ? '<span class="chip hot">程序已锁定，烧制中</span>' : ''}
      ${state.role !== 'admin' && ['loaded', 'interrupted'].includes(detail.status)
        ? '<span class="muted">当前角色无点火权限，可切换右上角“管理员”演示</span>' : ''}
    </div>
  </div>
  <div class="panel">
    <h2>程序步骤</h2>
    <table><thead><tr><th>#</th><th>升温速率</th><th>目标温度</th><th>保温</th></tr></thead>
    <tbody>${JSON.parse(detail.program.steps_json).map((s, i) =>
      `<tr><td>${i + 1}</td><td>${s.ramp}°C/h</td><td>${s.target}°C</td><td>${s.hold}min</td></tr>`).join('')}</tbody></table>
  </div>`;

  main.querySelector('#sel-batch').addEventListener('change', (e) => {
    state.selectedBatch = Number(e.target.value);
    localStorage.setItem('batch', state.selectedBatch);
    render();
  });
  const btn = main.querySelector('#btn-ignite');
  if (btn) btn.addEventListener('click', async () => {
    if (!confirm(`确认以「${detail.program_name}」点火？点火后批次与程序锁定。`)) return;
    try { await api('POST', `/api/batches/${state.selectedBatch}/ignite`); ok('已点火，批次与程序锁定'); }
    catch (e) { err(e); }
    render();
  });
}

/** 温度程序阶梯曲线 SVG */
function curveSvg(curve, tempInfo) {
  const W = 640, H = 280, ml = 46, mb = 30, mt = 14, mr = 14;
  const iw = W - ml - mr, ih = H - mt - mb;
  const maxT = curve.points[curve.points.length - 1].t;
  const maxTemp = curve.peak * 1.12;
  const X = (t) => ml + (t / maxT) * iw;
  const Y = (temp) => mt + ih - (temp / maxTemp) * ih;
  const path = curve.points.map((p, i) => `${i === 0 ? 'M' : 'L'}${X(p.t).toFixed(1)},${Y(p.temp).toFixed(1)}`).join(' ');
  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((k) => Math.round(curve.peak * k / 100) * 100);
  const marker = tempInfo && tempInfo.phase !== 'cooled'
    ? (() => {
        const t = Math.min(tempInfo.elapsed_h, maxT);
        return `<circle cx="${X(t)}" cy="${Y(tempInfo.temp_c)}" r="5" fill="#e2601a" stroke="#fff" stroke-width="2">
          <title>当前 ${tempInfo.temp_c}°C</title></circle>
        <text x="${Math.min(X(t) + 8, W - 90)}" y="${Y(tempInfo.temp_c) - 8}" font-size="11" fill="#e2601a">${tempInfo.temp_c}°C</text>`;
      })()
    : '';
  return `<svg width="100%" viewBox="0 0 ${W} ${H}" style="max-width:720px;background:#fffdf8;border:1px solid var(--clay-line);border-radius:8px">
    ${yTicks.map((t) => `<line x1="${ml}" y1="${Y(t)}" x2="${W - mr}" y2="${Y(t)}" stroke="#eee5d5"/>
      <text x="${ml - 6}" y="${Y(t) + 4}" text-anchor="end" font-size="10" fill="#8a7a66">${t}°</text>`).join('')}
    <line x1="${ml}" y1="${mt + ih}" x2="${W - mr}" y2="${mt + ih}" stroke="#c9b99a"/>
    <text x="${W - mr}" y="${H - 8}" text-anchor="end" font-size="10" fill="#8a7a66">时间（h）0 → ${maxT.toFixed(1)}</text>
    <path d="${path}" fill="none" stroke="#e2601a" stroke-width="2.5"/>
    ${curve.points.map((p) => `<circle cx="${X(p.t)}" cy="${Y(p.temp)}" r="3" fill="#2f6f8f"/>`).join('')}
    ${marker}
  </svg>`;
}

/* ================= 冷却计时 ================= */

async function renderCooling(main) {
  const list = await api('GET', '/api/cooling');
  main.innerHTML = `
  <div class="panel">
    <h2>冷却计时 <span class="en">完全冷却后才能开窑；提前开窑需管理员并留痕</span></h2>
    ${list.length === 0 ? '<p class="muted">当前没有烧制/冷却中的批次。</p>' : `
    <table><thead><tr>
      <th>批次</th><th>窑炉</th><th>状态</th><th>点火时间</th><th>完全冷却时点</th><th>剩余</th><th>操作</th>
    </tr></thead><tbody>
      ${list.map((b) => `<tr>
        <td><b>${esc(b.name)}</b><br><span class="muted">${KIND_LABEL[b.kind]} · ${b.item_count} 件</span></td>
        <td>${esc(b.kiln_name)}</td>
        <td>${batchChip(b.status)}</td>
        <td>${fmtT(b.ignited_at)}</td>
        <td>${fmtT(b.cooled_until)}</td>
        <td>${b.status === 'cooled' ? '<span class="chip ok">可开窑</span>'
          : b.status === 'interrupted' ? '<span class="chip bad">已中断</span>'
          : `<span class="countdown" data-cd="${b.cooled_until}">—</span>`}</td>
        <td>
          ${['cooling', 'cooled', 'firing'].includes(b.status)
            ? `<button class="small" data-open="${b.id}">${b.status === 'cooled' ? '开窑' : '提前开窑'}</button>` : ''}
          ${b.status === 'interrupted' && state.role === 'admin'
            ? `<button class="small blue" data-reignite="${b.id}">恢复供电·重新点火</button>` : ''}
        </td>
      </tr>`).join('')}
    </tbody></table>`}
  </div>
  ${state.role === 'admin' ? `
  <div class="panel">
    <h2>停电模拟 <span class="en">管理员 · 用于演练停电中断留痕</span></h2>
    <div class="flex">
      ${state.meta.kilns.map((k) => `<button class="ghost" data-outage="${k.id}">${esc(k.name)} 停电</button>`).join('')}
    </div>
  </div>` : ''}`;

  main.querySelectorAll('[data-open]').forEach((b) => b.addEventListener('click', async () => {
    const id = b.dataset.open;
    if (b.textContent.includes('提前') && !confirm('批次尚未完全冷却！提前开窑将留痕「开窑过早」，且需要管理员权限。继续？')) return;
    try { await api('POST', `/api/batches/${id}/open`); ok('已开窑，请前往出窑清点'); }
    catch (e) { err(e); }
    render();
  }));
  main.querySelectorAll('[data-reignite]').forEach((b) => b.addEventListener('click', async () => {
    try { await api('POST', `/api/batches/${b.dataset.reignite}/ignite`); ok('已重新点火'); }
    catch (e) { err(e); }
    render();
  }));
  main.querySelectorAll('[data-outage]').forEach((b) => b.addEventListener('click', async () => {
    try { await api('POST', `/api/kilns/${b.dataset.outage}/power-outage`, { note: '模拟突发停电' }); ok('已记录停电中断'); }
    catch (e) { err(e); }
    render();
  }));
}

/* ================= 出窑清点 ================= */

async function renderCounting(main) {
  const batches = await api('GET', '/api/batches');
  const opened = batches.filter((b) => b.status === 'opened');
  const closed = batches.filter((b) => b.status === 'closed');
  let html = `
  <div class="panel">
    <h2>出窑清点 <span class="en">逐件登记 完好 / 裂损 / 少件，全部清点完批次关闭</span></h2>
    ${opened.length === 0 ? '<p class="muted">没有待清点的批次（需先在冷却计时中开窑）。</p>' : ''}
  </div>`;

  for (const b of opened) {
    const detail = await api('GET', `/api/batches/${b.id}`);
    html += `
    <div class="panel">
      <h2>${esc(b.name)} ${b.opened_early ? '<span class="event-badge severe">开窑过早</span>' : ''}</h2>
      <form data-count="${b.id}">
        <table><thead><tr><th>代号</th><th>学生</th><th>尺寸(mm)</th><th>釉色</th><th>结果</th><th>备注</th></tr></thead>
        <tbody>${detail.items.map((it) => `<tr>
          <td><b>${it.work_code}</b></td><td>${it.student_code}</td>
          <td>${it.width_mm}×${it.depth_mm}×${it.height_mm}</td><td>${it.glaze_name || '—'}</td>
          <td>
            <label><input type="radio" name="r-${it.work_id}" value="intact" checked> 完好</label>
            <label><input type="radio" name="r-${it.work_id}" value="cracked"> 裂损</label>
            <label><input type="radio" name="r-${it.work_id}" value="missing"> 少件</label>
          </td>
          <td><input name="n-${it.work_id}" placeholder="裂损/少件说明" style="width:180px"></td>
        </tr>`).join('')}</tbody></table>
        <div class="mt8"><button>提交清点</button></div>
      </form>
    </div>`;
  }

  html += `<div class="panel"><h2>已关闭批次</h2>
    ${closed.length === 0 ? '<p class="muted">暂无。</p>' : closed.map((b) =>
      `<p><b>${esc(b.name)}</b> ${batchChip(b.status)} <span class="muted">${b.item_count} 件 · ${fmtT(b.opened_at)} 开窑</span>
       <button class="small ghost" data-detail="${b.id}">查看结果</button></p>`).join('')}
    <div id="closed-detail"></div>
  </div>`;
  main.innerHTML = html;

  main.querySelectorAll('[data-count]').forEach((f) => f.addEventListener('submit', async (e) => {
    e.preventDefault();
    const batchId = f.dataset.count;
    const detail = await api('GET', `/api/batches/${batchId}`);
    const fd = new FormData(f);
    const results = detail.items.map((it) => ({
      work_id: it.work_id, result: fd.get(`r-${it.work_id}`), note: fd.get(`n-${it.work_id}`) || '',
    }));
    try { await api('POST', `/api/batches/${batchId}/count`, { results }); ok('清点完成，批次已关闭'); }
    catch (e2) { err(e2); }
    render();
  }));
  main.querySelectorAll('[data-detail]').forEach((b) => b.addEventListener('click', async () => {
    const detail = await api('GET', `/api/batches/${b.dataset.detail}`);
    const box = main.querySelector('#closed-detail');
    box.innerHTML = `<h3>${esc(detail.name)} 清点结果</h3>
      <table><thead><tr><th>代号</th><th>结果</th><th>备注</th><th>成品照片</th></tr></thead>
      <tbody>${detail.items.map((it) => `<tr>
        <td>${it.work_code}</td>
        <td>${{ intact: '<span class="chip ok">完好</span>', cracked: '<span class="chip bad">裂损</span>', missing: '<span class="chip bad">少件</span>', pending: '—' }[it.result]}</td>
        <td>${esc(it.damage_note || '')}</td>
        <td>${it.result === 'intact' && it.stage !== 'bisque' ? `<input type="file" data-photo="${it.work_id}" accept=".svg,.png,.jpg,.jpeg" style="font-size:11px">` : '—'}</td>
      </tr>`).join('')}</tbody></table>`;
    box.querySelectorAll('[data-photo]').forEach((inp) => inp.addEventListener('change', async () => {
      if (!inp.files[0]) return;
      try {
        await uploadPhoto('work', Number(inp.dataset.photo), 'product', inp.files[0]);
        ok('成品照片已上传（学生端可见）');
      } catch (e2) { err(e2); }
    }));
  }));
}

/* ================= 补烧追踪 ================= */

async function renderRefires(main) {
  const [refires, works, batches] = await Promise.all([
    api('GET', '/api/refires'), api('GET', '/api/works'), api('GET', '/api/batches'),
  ]);
  const damaged = works.filter((w) => w.status === 'damaged');
  main.innerHTML = `
  <div class="panel">
    <h2>补烧追踪 <span class="en">补烧必须引用原作品与失败原因</span></h2>
    ${refires.length === 0 ? '<p class="muted">暂无补烧单。</p>' : `
    <table><thead><tr><th>#</th><th>作品</th><th>原批次（失败来源）</th><th>失败原因</th><th>新批次</th><th>状态</th></tr></thead>
    <tbody>${refires.map((r) => `<tr>
      <td>${r.id}</td><td><b>${r.work_code}</b></td><td>${esc(r.source_batch_name)}</td>
      <td>${esc(r.reason)}</td><td>${r.new_batch_name ? esc(r.new_batch_name) : '<span class="muted">待排入</span>'}</td>
      <td>${{ pending: '<span class="chip hot">待排入</span>', scheduled: '<span class="chip">已排入</span>', done: '<span class="chip ok">补烧完成</span>' }[r.status]}</td>
    </tr>`).join('')}</tbody></table>`}
  </div>
  <div class="panel">
    <h2>新建补烧单 <span class="en">仅裂损作品可补烧</span></h2>
    ${damaged.length === 0 ? '<p class="muted">当前没有裂损待补烧的作品。</p>' : `
    <form id="f-refire" class="flex">
      <label class="field">裂损作品
        <select name="work_id">${damaged.map((w) => `<option value="${w.id}">${w.code}（${w.student_code}）</option>`).join('')}</select>
      </label>
      <label class="field">失败原因<input name="reason" style="width:260px" placeholder="如：底足开裂，修坯后补烧" required></label>
      <button>创建补烧单</button>
    </form>`}
  </div>`;

  const f = main.querySelector('#f-refire');
  if (f) f.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fd = new FormData(f);
    const workId = Number(fd.get('work_id'));
    // 找到该作品裂损所在的批次
    const source = batches.find((b) => b.status === 'closed');
    let sourceBatchId = source?.id;
    for (const b of batches) {
      const d = await api('GET', `/api/batches/${b.id}`);
      if (d.items.some((it) => it.work_id === workId && it.result === 'cracked')) { sourceBatchId = b.id; break; }
    }
    try {
      await api('POST', '/api/refires', { work_id: workId, source_batch_id: sourceBatchId, reason: fd.get('reason') });
      ok('补烧单已创建');
      render();
    } catch (e2) { err(e2); }
  });
}

/* ================= 留痕记录 ================= */

async function renderEvents(main) {
  const anomalies = await api('GET', '/api/events?anomalies=1');
  const all = await api('GET', '/api/events');
  main.innerHTML = `
  <div class="panel">
    <h2>异常留痕 <span class="en">标签脱落 / 干燥不足 / 釉料相冲 / 装载超高 / 停电中断 / 开窑过早 / 裂损 / 少件</span></h2>
    ${eventList(anomalies)}
  </div>
  <div class="panel">
    <h2>全部事件流水</h2>
    ${eventList(all)}
  </div>`;
}

function eventList(events) {
  if (!events.length) return '<p class="muted">暂无记录。</p>';
  return `<table><thead><tr><th>时间</th><th>类型</th><th>对象</th><th>详情</th><th>操作人</th></tr></thead>
  <tbody>${events.map((e) => `<tr>
    <td class="muted">${fmtT(e.created_at)}</td>
    <td>${eventBadge(e.type)}</td>
    <td>${e.entity_type}#${e.entity_id}</td>
    <td>${esc(e.detail || '')}</td>
    <td>${esc(e.actor || '—')}</td>
  </tr>`).join('')}</tbody></table>`;
}

/* ================= 学生端（只读进度 + 成品照片） ================= */

async function renderStudent(main) {
  main.innerHTML = `
  <div class="panel">
    <h2>学生作品查询 <span class="en">输入匿名代号，仅展示作品进度与成品照片</span></h2>
    <form id="f-stu" class="flex">
      <label class="field">我的代号<input name="code" value="${esc(state.studentCode)}" placeholder="如 S3-01"></label>
      <button class="blue">查询</button>
    </form>
    <div id="stu-result"></div>
  </div>`;
  const show = async (code) => {
    const box = main.querySelector('#stu-result');
    try {
      const data = await api('GET', `/api/student/${encodeURIComponent(code)}`);
      box.innerHTML = `
        <h3>${esc(data.student.code)}（${esc(data.student.class_name)}）的作品</h3>
        ${data.works.length === 0 ? '<p class="muted">还没有作品。</p>' : data.works.map((w) => `
          <div class="panel" style="background:#fbf7ef">
            <div class="flex">
              <b>${w.code}</b>
              <span class="chip">${w.progress.current}</span>
              <span class="muted">${w.clay_name} · ${w.width_mm}×${w.depth_mm}×${w.height_mm}mm ${w.glaze_name ? '· ' + w.glaze_name : ''}</span>
            </div>
            <div class="steps">
              ${w.progress.steps.map((s, i) =>
                `<div class="step ${i < w.progress.index ? 'done' : i === w.progress.index ? 'now' : ''}">${s}</div>`).join('')}
            </div>
            ${w.product_photos.length ? `<div class="photo-grid">${w.product_photos.map((p) => `<img src="${p}" alt="成品照片">`).join('')}</div>` : ''}
          </div>`).join('')}`;
    } catch (e) {
      box.innerHTML = `<p class="warn-text">${esc(e.message)}</p>`;
    }
  };
  main.querySelector('#f-stu').addEventListener('submit', (e) => {
    e.preventDefault();
    state.studentCode = new FormData(e.target).get('code').trim();
    localStorage.setItem('studentCode', state.studentCode);
    show(state.studentCode);
  });
  if (state.studentCode) show(state.studentCode);
}

/* ================= 照片上传 ================= */

function uploadPhoto(ownerType, ownerId, kind, file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = async () => {
      try {
        const base64 = String(reader.result).split(',')[1] || '';
        resolve(await api('POST', '/api/photos', {
          owner_type: ownerType, owner_id: ownerId, kind,
          filename: file.name, data_base64: base64,
        }));
      } catch (e) { reject(e); }
    };
    reader.onerror = () => reject(new Error('读取文件失败'));
    reader.readAsDataURL(file);
  });
}

/* ================= 倒计时跳动 ================= */

setInterval(() => {
  document.querySelectorAll('[data-cd]').forEach((el) => {
    const target = new Date(el.dataset.cd).getTime();
    const diff = target - Date.now();
    if (diff <= 0) { el.textContent = '已到时'; return; }
    const h = Math.floor(diff / 3600e3);
    const m = Math.floor((diff % 3600e3) / 60e3);
    const s = Math.floor((diff % 60e3) / 1e3);
    el.textContent = `${h}h ${String(m).padStart(2, '0')}m ${String(s).padStart(2, '0')}s`;
  });
}, 1000);

render();
