"""页面渲染：服务端 HTML + SVG（棚板圆形俯视、程序阶梯曲线）。

配色：陶土白底、窑火橙主色、釉蓝辅色。学生端只展示作品进度与成品照片。
"""
from __future__ import annotations

import html
import math
from datetime import datetime, timedelta

from . import domain
from .services import (
    BATCH_STATUS_LABELS,
    INCIDENT_LABELS,
    WORK_STATUS_LABELS,
)

# ---------------------------------------------------------------- 基础


def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))


def fmt(s: str | None) -> str:
    return domain.fmt_dt(s)


def work_badge(status: str) -> str:
    cls = {
        "drying": "b-dry", "dry_qualified": "b-ok", "scheduled": "b-plan",
        "firing": "b-fire", "completed": "b-done", "damaged": "b-bad",
        "missing": "b-bad", "refire_pending": "b-warn",
    }.get(status, "b-plan")
    return f'<span class="badge {cls}">{esc(WORK_STATUS_LABELS.get(status, status))}</span>'


def batch_badge(status: str) -> str:
    cls = {
        "scheduled": "b-plan", "firing": "b-fire", "cooling": "b-cool",
        "cooled": "b-ok", "opened": "b-done", "interrupted": "b-bad",
    }.get(status, "b-plan")
    return f'<span class="badge {cls}">{esc(BATCH_STATUS_LABELS.get(status, status))}</span>'


def incident_badge(inc_type: str) -> str:
    cls = {
        "label_detached": "b-warn", "insufficient_drying": "b-warn",
        "glaze_conflict": "b-bad", "over_height": "b-bad",
        "power_outage": "b-bad", "power_restored": "b-ok",
        "early_open": "b-bad", "crack": "b-bad", "missing_piece": "b-bad",
    }.get(inc_type, "b-plan")
    return f'<span class="badge {cls}">{esc(INCIDENT_LABELS.get(inc_type, inc_type))}</span>'


def glaze_dot(color: str, name: str) -> str:
    return (f'<span class="glaze-dot" style="background:{esc(color)}" '
            f'title="{esc(name)}"></span>{esc(name)}')


NAV = [
    ("/", "首页"),
    ("/works", "作品登记"),
    ("/drying", "干燥队列"),
    ("/calendar", "窑炉日历"),
    ("/incidents", "异常留痕"),
    ("/refires", "补烧追踪"),
]

ROLE_LABELS = {"admin": "管理员", "teacher": "教师", "student": "学生"}


def layout(title: str, user: dict | None, body: str, active: str = "") -> str:
    nav = ""
    if user and user["role"] in ("admin", "teacher"):
        nav = "".join(
            f'<a href="{href}" class="{"on" if active == href else ""}">{label}</a>'
            for href, label in NAV)
    elif user and user["role"] == "student":
        nav = f'<a href="/student" class="{"on" if active == "/student" else ""}">我的作品</a>'
    user_bar = ""
    if user:
        user_bar = (f'<span class="who">{esc(user["display_name"])}'
                    f'<em>{ROLE_LABELS.get(user["role"], user["role"])}</em></span>'
                    f'<a class="btn ghost sm" href="/logout">退出</a>')
    else:
        user_bar = '<a class="btn ghost sm" href="/login">登录</a>'
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} · 陶艺窑炉排期系统</title>
<link rel="stylesheet" href="/static/style.css">
</head>
<body>
<header class="topbar">
  <div class="brand"><span class="logo">🏺</span> 小学陶艺教室 · 窑炉排期与烧制批次系统</div>
  <nav>{nav}</nav>
  <div class="userbar">{user_bar}</div>
</header>
<main class="wrap">
{body}
</main>
<footer class="foot">陶土白 · 窑火橙 · 釉蓝 —— 本地演示系统，学生信息均为匿名代号</footer>
<script src="/static/app.js"></script>
</body>
</html>"""


def error_page(title: str, message: str, user=None, status_hint: str = "") -> str:
    body = f"""
<div class="card error-card">
  <h2>⚠ {esc(title)}</h2>
  <p>{esc(message)}</p>
  <p class="muted">{esc(status_hint)}</p>
  <p><a class="btn" href="javascript:history.back()">返回上一页</a>
     <a class="btn ghost" href="/">回到首页</a></p>
</div>"""
    return layout(title, user, body)


# ---------------------------------------------------------------- SVG：棚板圆形俯视


def _slot_positions(n: int) -> list[tuple[float, float]]:
    """单位圆内工位：中心 1 + 每环 6k 个。"""
    pos = [(0.0, 0.0)]
    ring = 1
    while len(pos) < n:
        count = 6 * ring
        r = 0.30 * ring
        for i in range(count):
            a = 2 * math.pi * i / count - math.pi / 2
            pos.append((r * math.cos(a), r * math.sin(a)))
        ring += 1
    return pos[:n]


def shelf_layout_svg(kiln: dict, items: list[dict], shelf_no: int) -> str:
    """圆形棚板俯视示意：作品用编号+尺寸小块表示，颜色取自釉色。"""
    slots = _slot_positions(kiln["shelf_slots"])
    by_slot = {it["slot_no"]: it for it in items if it["shelf_no"] == shelf_no}
    parts = [f'<circle cx="0" cy="0" r="112" fill="#efe6d6" stroke="#b09a7c" stroke-width="3"/>',
             f'<circle cx="0" cy="0" r="104" fill="none" stroke="#d8cbb2" stroke-width="1"'
             f' stroke-dasharray="4 4"/>']
    for idx, (x, y) in enumerate(slots, start=1):
        cx, cy = x * 100, y * 100
        item = by_slot.get(idx)
        if item is None:
            parts.append(f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="15" fill="none"'
                         f' stroke="#cbbfa8" stroke-width="1.4" stroke-dasharray="3 3"/>')
            continue
        warn = ' stroke="#c0392b" stroke-width="2.5" stroke-dasharray="4 2"' \
            if item["label_detached"] else ' stroke="#3b332b" stroke-width="1.6"'
        dims = f'{item["width_cm"]:.0f}×{item["depth_cm"]:.0f}×{item["height_cm"]:.0f}'
        parts.append(
            f'<g><rect x="{cx - 21:.0f}" y="{cy - 15:.0f}" width="42" height="30" rx="6"'
            f' fill="{esc(item["color_hex"])}"{warn}>'
            f'<title>{esc(item["code"])} · {esc(item["anon_code"])} · {dims}cm · '
            f'{esc(item["glaze_name"])}</title></rect>'
            f'<text x="{cx:.0f}" y="{cy - 1:.0f}" text-anchor="middle" font-size="10.5"'
            f' font-weight="700" fill="#fff">{esc(item["code"])}</text>'
            f'<text x="{cx:.0f}" y="{cy + 10:.0f}" text-anchor="middle" font-size="8"'
            f' fill="#fff">{dims}</text></g>')
    return (f'<svg class="shelf-svg" viewBox="-120 -120 240 240" role="img"'
            f' aria-label="第{shelf_no}层棚板俯视">{"".join(parts)}</svg>')


# ---------------------------------------------------------------- SVG：程序阶梯曲线


def program_curve_svg(segments: list[dict], batch: dict | None = None,
                      current: dict | None = None) -> str:
    """温度程序阶梯曲线；批次点火后叠加当前温度点与冷却段。"""
    points = domain.profile_points(segments)
    total_min = points[-1][0]
    max_temp = max(domain.program_max_temp(segments), 100)
    cooling_min = 0.0
    if batch and batch.get("ignited_at") and batch.get("cooled_at") and batch.get("firing_end_at"):
        cooled_at = domain.parse_dt(batch["cooled_at"])
        firing_end = domain.parse_dt(batch["firing_end_at"])
        cooling_min = (cooled_at - firing_end).total_seconds() / 60.0
        points = points + [(total_min + cooling_min, domain.AMBIENT_C)]
    x_max = total_min + cooling_min
    x_max = max(x_max, 60)
    y_max = max_temp * 1.15

    W, H, ml, mr, mt, mb = 680, 280, 56, 16, 18, 40
    pw, ph = W - ml - mr, H - mt - mb

    def X(m):
        return ml + pw * m / x_max

    def Y(t):
        return mt + ph * (1 - t / y_max)

    grid = []
    step = 200 if y_max > 500 else 100
    t = 0
    while t <= y_max:
        grid.append(f'<line x1="{ml}" y1="{Y(t):.1f}" x2="{W - mr}" y2="{Y(t):.1f}"'
                    f' class="grid"/>'
                    f'<text x="{ml - 6}" y="{Y(t) + 4:.1f}" text-anchor="end"'
                    f' class="axis-label">{t:.0f}</text>')
        t += step
    n_ticks = 6
    for i in range(n_ticks + 1):
        m = x_max * i / n_ticks
        grid.append(f'<text x="{X(m):.1f}" y="{H - mb + 16}" text-anchor="middle"'
                    f' class="axis-label">{m / 60:.1f}h</text>')

    poly = " ".join(f"{X(m):.1f},{Y(t):.1f}" for m, t in points)
    curve = [f'<polyline points="{poly}" fill="none" class="curve"/>']
    for m, t in points:
        curve.append(f'<circle cx="{X(m):.1f}" cy="{Y(t):.1f}" r="3.4" class="curve-dot"/>')
    # 段标注
    acc = 0.0
    temp = domain.AMBIENT_C
    for seg in segments:
        if "rate" in seg:
            target = float(seg["target"])
            dur = abs(target - temp) / float(seg["rate"]) * 60.0
            mid = acc + dur / 2
            curve.append(f'<text x="{X(mid):.1f}" y="{Y((temp + target) / 2) - 7:.1f}"'
                         f' text-anchor="middle" class="seg-label">{target:.0f}°C</text>')
            acc += dur
            temp = target
        else:
            dur = float(seg["hold"])
            acc += dur
    if cooling_min > 0:
        curve.append(f'<text x="{X(total_min + cooling_min / 2):.1f}"'
                     f' y="{Y(domain.AMBIENT_C) - 26:.1f}" text-anchor="middle"'
                     f' class="seg-label cool">自然冷却</text>')
    # 当前温度点
    if current and batch and batch.get("ignited_at"):
        ignited = domain.parse_dt(batch["ignited_at"])
        now = datetime.now()
        elapsed = (now - ignited).total_seconds() / 60.0
        cx, cy = X(min(elapsed, x_max)), Y(min(current["temp"], y_max))
        curve.append(f'<line x1="{cx:.1f}" y1="{mt}" x2="{cx:.1f}" y2="{H - mb}"'
                     f' class="now-line"/>')
        curve.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="6" class="now-dot"/>')
        curve.append(f'<text x="{cx:.1f}" y="{cy - 12:.1f}" text-anchor="middle"'
                     f' class="now-label">{current["temp"]:.0f}°C</text>')
    return (f'<svg class="curve-svg" viewBox="0 0 {W} {H}" role="img" aria-label="温度程序曲线">'
            f'{"".join(grid)}{"".join(curve)}'
            f'<text x="{ml}" y="{H - 6}" class="axis-label">时间</text>'
            f'<text x="8" y="{mt + 4}" class="axis-label">°C</text></svg>')


# ---------------------------------------------------------------- 页面：登录


def login_page(users: list[dict], user=None) -> str:
    buttons = []
    for u in users:
        role_cls = {"admin": "role-admin", "teacher": "role-teacher", "student": "role-student"}[u["role"]]
        buttons.append(f"""
        <form method="post" action="/login" class="login-item">
          <input type="hidden" name="user_id" value="{u['id']}">
          <button class="login-btn {role_cls}" type="submit">
            <strong>{esc(u['display_name'])}</strong>
            <span>{ROLE_LABELS.get(u['role'], u['role'])}</span>
          </button>
        </form>""")
    body = f"""
<div class="card login-card">
  <h2>选择身份登录</h2>
  <p class="muted">本地演示系统，免密码。管理员可点火与异常开窑；教师可排期与装窑；学生仅查看自己的作品进度。</p>
  <div class="login-grid">{''.join(buttons)}</div>
</div>"""
    return layout("登录", user, body)


# ---------------------------------------------------------------- 页面：首页


def dashboard(cards: list[dict], counts: dict, recent: list[dict], user: dict) -> str:
    kiln_cards = []
    for card in cards:
        kiln, active, upcoming = card["kiln"], card["active"], card["upcoming"]
        if active:
            state = (f'{batch_badge(active["status"])} '
                     f'<a href="/batches/{active["id"]}">{esc(active["name"])}</a>')
            temp_line = (f'<div class="temp-line" data-temp-kiln="{kiln["id"]}">'
                         f'<span class="temp-num">--</span><span class="temp-unit">°C</span>'
                         f'<span class="temp-phase"></span></div>')
        else:
            state = '<span class="badge b-done">空闲</span>'
            temp_line = '<div class="temp-line idle"><span class="temp-num">25</span>' \
                        '<span class="temp-unit">°C</span><span class="temp-phase">室温</span></div>'
        up = (f'<div class="muted small">下一批：{esc(upcoming["name"])} '
              f'{fmt(upcoming["scheduled_start"])}</div>') if upcoming else ""
        kiln_cards.append(f"""
    <div class="card kiln-card">
      <h3>{esc(kiln['name'])}</h3>
      {temp_line}
      <div class="kiln-meta">{kiln['shelf_count']} 层棚板 · Ø{kiln['shelf_diameter_cm']:.0f}cm
        · 层净高 {kiln['shelf_clearance_cm']:.0f}cm</div>
      <div class="kiln-state">{state}</div>
      {up}
    </div>""")
    stats = f"""
    <div class="stat"><b>{counts['drying']}</b><span>干燥中作品</span></div>
    <div class="stat"><b>{counts['qualified']}</b><span>待装窑</span></div>
    <div class="stat"><b>{counts['active_batches']}</b><span>烧制/冷却批次</span></div>
    <div class="stat"><b>{counts['refire_pending']}</b><span>待补烧</span></div>
    <div class="stat"><b>{counts['incidents']}</b><span>异常留痕</span></div>"""
    recent_rows = "".join(
        f'<tr><td>{incident_badge(i["type"])}</td>'
        f'<td>{esc(i["detail"])}</td>'
        f'<td class="muted">{esc(i["actor_name"] or "—")} · {fmt(i["created_at"])}</td></tr>'
        for i in recent)
    body = f"""
<h2 class="page-title">窑炉实况</h2>
<div class="kiln-grid">{''.join(kiln_cards)}</div>
<div class="stat-grid">{stats}</div>
<div class="card">
  <h3>最新异常留痕</h3>
  <table class="tbl"><tbody>{recent_rows or '<tr><td class="muted">暂无异常</td></tr>'}</tbody></table>
  <p><a href="/incidents">查看全部 →</a></p>
</div>"""
    return layout("首页", user, body, "/")


# ---------------------------------------------------------------- 页面：作品登记与列表


def works_page(works: list[dict], options: dict, user: dict, msg: str = "") -> str:
    form = ""
    if user["role"] in ("admin", "teacher"):
        student_opts = "".join(
            f'<option value="{s["id"]}">{esc(s["anon_code"])}（{esc(s["class_name"])}）</option>'
            for s in options["students"])
        clay_opts = "".join(f'<option value="{c["id"]}">{esc(c["name"])}</option>'
                            for c in options["clays"])
        glaze_opts = "".join(f'<option value="{g["id"]}">{esc(g["name"])}</option>'
                             for g in options["glazes"])
        form = f"""
<div class="card">
  <h3>作品登记 <span class="muted small">登记后即进入自然干燥（默认 48 小时）</span></h3>
  <form method="post" action="/works" class="form-grid">
    <label>学生代号<select name="student_id">{student_opts}</select></label>
    <label>泥料<select name="clay_id">{clay_opts}</select></label>
    <label>釉色<select name="glaze_id">{glaze_opts}</select></label>
    <label>宽 cm<input name="width" type="number" step="0.5" min="1" value="12" required></label>
    <label>深 cm<input name="depth" type="number" step="0.5" min="1" value="12" required></label>
    <label>高 cm<input name="height" type="number" step="0.5" min="1" value="15" required></label>
    <label>干燥要求 h<input name="drying_hours" type="number" step="1" min="1" value="48" required></label>
    <div class="form-actions"><button class="btn" type="submit">登记并进入干燥</button></div>
  </form>
</div>"""
    rows = []
    for w in works:
        label_mark = ' <span class="badge b-warn">标签脱落</span>' if w["label_detached"] else ""
        rows.append(f"""
    <tr>
      <td><a href="/works/{w['id']}"><b>{esc(w['code'])}</b></a>{label_mark}</td>
      <td>{esc(w['anon_code'])} · {esc(w['class_name'])}</td>
      <td>{esc(w['clay_name'])}</td>
      <td>{glaze_dot(w['color_hex'], w['glaze_name'])}</td>
      <td>{w['width_cm']:.0f}×{w['depth_cm']:.0f}×{w['height_cm']:.0f}</td>
      <td>{work_badge(w['status'])}</td>
    </tr>""")
    notice = f'<div class="notice">{esc(msg)}</div>' if msg else ""
    body = f"""
<h2 class="page-title">作品登记</h2>
{notice}
{form}
<div class="card">
  <h3>全部作品</h3>
  <table class="tbl">
    <thead><tr><th>代号</th><th>学生</th><th>泥料</th><th>釉色</th><th>尺寸(cm)</th><th>状态</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</div>"""
    return layout("作品登记", user, body, "/works")


def work_detail_page(chain: dict, user: dict, msg: str = "") -> str:
    w = chain["work"]
    stages = ["drying", "dry_qualified", "scheduled", "firing", "completed"]
    labels = ["自然干燥", "干燥合格", "装窑排烧", "烧制冷却", "出窑成品"]
    if w["status"] in ("damaged", "missing", "refire_pending"):
        stage_idx = 4
    else:
        stage_idx = stages.index(w["status"]) if w["status"] in stages else 0
    timeline = "".join(
        f'<li class="{"done" if i <= stage_idx else ""}"><i></i>{label}</li>'
        for i, label in enumerate(labels))
    label_mark = ' <span class="badge b-warn">标签脱落</span>' if w["label_detached"] else ""
    items_rows = "".join(
        f'<tr><td><a href="/batches/{i["batch_id"]}">{esc(i["batch_name"])}</a></td>'
        f'<td>{esc(i["kiln_name"])}</td><td>第 {i["shelf_no"]} 层 · 位 {i["slot_no"]}</td>'
        f'<td>{batch_badge(i["batch_status"])}</td>'
        f'<td>{esc({"ok": "完好", "cracked": "裂损", "missing": "少件"}.get(i["result"], "—"))}'
        f'{"（" + esc(i["result_note"]) + "）" if i["result_note"] else ""}</td></tr>'
        for i in chain["items"])
    incident_rows = "".join(
        f'<tr><td>{incident_badge(i["type"])}</td><td>{esc(i["detail"])}</td>'
        f'<td class="muted">{esc(i["actor_name"] or "—")} · {fmt(i["created_at"])}</td></tr>'
        for i in chain["incidents"])
    photos = "".join(
        f'<figure class="photo"><img src="/photos/{esc(p["filename"])}" alt="作品照片">'
        f'<figcaption>{"装窑" if p["kind"] == "loading" else "成品"} · {fmt(p["created_at"])}</figcaption></figure>'
        for p in chain["photos"])
    refire_rows = "".join(
        f'<tr><td>{esc(r["reason"])}</td><td>{esc(r["source_batch_name"])}</td>'
        f'<td>{esc(r["new_batch_name"] or "—")}</td>'
        f'<td>{esc({"pending": "待安排", "scheduled": "已排入批次", "done": "补烧完成"}.get(r["status"], r["status"]))}</td></tr>'
        for r in chain["refires"])

    actions = []
    if user["role"] in ("admin", "teacher"):
        if not w["label_detached"]:
            actions.append(f"""
      <form method="post" action="/works/{w['id']}/label" class="inline"
            onsubmit="return confirm('确认该作品标签脱落？将留痕记录。')">
        <button class="btn warn sm" type="submit">标记标签脱落</button></form>""")
        if w["status"] == "damaged":
            actions.append(f"""
      <form method="post" action="/works/{w['id']}/refire" class="inline-flex">
        <input name="reason" placeholder="失败原因（必填）" required>
        <button class="btn sm" type="submit">创建补烧</button></form>""")
        if w["status"] == "completed":
            actions.append(f"""
      <div class="inline-flex"><input type="file" id="photo-file" accept="image/*">
        <button class="btn sm" data-upload-photo kind="finished" work-id="{w['id']}">上传成品照片</button></div>""")
    notice = f'<div class="notice">{esc(msg)}</div>' if msg else ""
    body = f"""
<h2 class="page-title">作品 {esc(w['code'])} {work_badge(w['status'])}{label_mark}</h2>
{notice}
<div class="two-col">
  <div class="card">
    <h3>作品档案</h3>
    <table class="kv">
      <tr><th>学生</th><td>{esc(chain['student']['anon_code'])} · {esc(chain['student']['class_name'])}</td></tr>
      <tr><th>泥料</th><td>{esc(chain['clay']['name'])}</td></tr>
      <tr><th>釉色</th><td>{glaze_dot(chain['glaze']['color_hex'], chain['glaze']['name'])}</td></tr>
      <tr><th>尺寸</th><td>{w['width_cm']:.0f} × {w['depth_cm']:.0f} × {w['height_cm']:.0f} cm</td></tr>
      <tr><th>干燥</th><td>{fmt(w['drying_started_at'])} 开始 · 要求 {w['drying_required_hours']:.0f}h
        · 确认于 {fmt(w['drying_confirmed_at'])}</td></tr>
      <tr><th>登记时间</th><td>{fmt(w['created_at'])}</td></tr>
    </table>
    <ol class="timeline">{timeline}</ol>
    <div class="actions">{''.join(actions)}</div>
  </div>
  <div class="card">
    <h3>烧制链路</h3>
    <table class="tbl"><thead><tr><th>批次</th><th>窑炉</th><th>位置</th><th>批次状态</th><th>出窑结果</th></tr></thead>
    <tbody>{items_rows or '<tr><td colspan="5" class="muted">尚未装窑</td></tr>'}</tbody></table>
    <h3>补烧记录</h3>
    <table class="tbl"><thead><tr><th>失败原因</th><th>原批次</th><th>补烧批次</th><th>状态</th></tr></thead>
    <tbody>{refire_rows or '<tr><td colspan="4" class="muted">无</td></tr>'}</tbody></table>
  </div>
</div>
<div class="two-col">
  <div class="card"><h3>照片</h3>
    <div class="photo-grid">{photos or '<p class="muted">暂无照片</p>'}</div></div>
  <div class="card"><h3>异常留痕</h3>
    <table class="tbl"><tbody>{incident_rows or '<tr><td class="muted">无</td></tr>'}</tbody></table></div>
</div>"""
    return layout(f"作品 {w['code']}", user, body, "/works")


# ---------------------------------------------------------------- 页面：干燥队列


def drying_page(queue: list[dict], user: dict, msg: str = "") -> str:
    rows = []
    for q in queue:
        pct = min(100.0, q["elapsed_hours"] / q["drying_required_hours"] * 100)
        if q["ready"]:
            remain = '<span class="badge b-ok">可确认</span>'
            action = (f'<form method="post" action="/drying/confirm" class="inline">'
                      f'<input type="hidden" name="work_id" value="{q["id"]}">'
                      f'<button class="btn sm" type="submit">确认干燥合格</button></form>'
                      if user["role"] in ("admin", "teacher") else "")
        else:
            remain = (f'<span data-countdown-hours="{q["remaining_hours"]:.2f}">'
                      f'还需 {q["remaining_hours"]:.1f}h</span>')
            action = (f'<form method="post" action="/drying/confirm" class="inline">'
                      f'<input type="hidden" name="work_id" value="{q["id"]}">'
                      f'<button class="btn sm ghost" type="submit">尝试确认</button></form>'
                      if user["role"] in ("admin", "teacher") else "")
        label_mark = ' <span class="badge b-warn">标签脱落</span>' if q["label_detached"] else ""
        rows.append(f"""
    <tr>
      <td><a href="/works/{q['id']}"><b>{esc(q['code'])}</b></a>{label_mark}</td>
      <td>{esc(q['anon_code'])} · {esc(q['class_name'])}</td>
      <td>{glaze_dot(q['color_hex'], q['glaze_name'])}</td>
      <td>{q['width_cm']:.0f}×{q['depth_cm']:.0f}×{q['height_cm']:.0f}</td>
      <td><div class="bar"><i style="width:{pct:.0f}%"></i></div>
          <span class="small muted">{q['elapsed_hours']:.1f} / {q['drying_required_hours']:.0f} h</span></td>
      <td>{remain}</td>
      <td>{action}</td>
    </tr>""")
    notice = f'<div class="notice">{esc(msg)}</div>' if msg else ""
    body = f"""
<h2 class="page-title">自然干燥队列</h2>
<p class="muted">作品登记后进入自然干燥；达到要求时长后由教师确认合格，方可排入素烧。提前确认会被拒绝并留痕。</p>
{notice}
<div class="card">
  <table class="tbl">
    <thead><tr><th>代号</th><th>学生</th><th>釉色</th><th>尺寸(cm)</th><th>干燥进度</th><th>状态</th><th>操作</th></tr></thead>
    <tbody>{''.join(rows) or '<tr><td colspan="7" class="muted">干燥队列为空</td></tr>'}</tbody>
  </table>
</div>"""
    return layout("干燥队列", user, body, "/drying")


# ---------------------------------------------------------------- 页面：窑炉日历


def calendar_page(kilns: list[dict], batches: list[dict], week_start: datetime,
                  week_offset: int, user: dict) -> str:
    days = [week_start + timedelta(days=i) for i in range(7)]
    head = "".join(f'<th>{d.strftime("%m-%d")}<br><span class="muted small">{["周一","周二","周三","周四","周五","周六","周日"][i]}</span></th>'
                   for i, d in enumerate(days))
    body_rows = []
    for kiln in kilns:
        cells = []
        for d in days:
            day_start = d
            day_end = d + timedelta(days=1)
            chips = []
            for b in batches:
                if b["kiln_id"] != kiln["id"]:
                    continue
                if domain.ranges_overlap(b["range_start"], b["range_end"], day_start, day_end):
                    chips.append(
                        f'<a class="cal-chip st-{b["status"]}" href="/batches/{b["id"]}">'
                        f'{esc(b["name"])}<br><span>{b["range_start"].strftime("%H:%M")}'
                        f'~{b["range_end"].strftime("%m-%d %H:%M")}</span></a>')
            cells.append(f'<td>{"".join(chips)}</td>')
        body_rows.append(f'<tr><th class="kiln-name">{esc(kiln["name"])}</th>{"".join(cells)}</tr>')
    new_btn = ('<a class="btn" href="/batches/new">+ 排期新批次</a>'
               if user["role"] in ("admin", "teacher") else "")
    body = f"""
<h2 class="page-title">窑炉日历</h2>
<div class="cal-nav">
  <a class="btn ghost sm" href="/calendar?w={week_offset - 1}">← 上一周</a>
  <b>{week_start.strftime('%Y-%m-%d')} 起的一周</b>
  <a class="btn ghost sm" href="/calendar?w={week_offset + 1}">下一周 →</a>
  <span class="spacer"></span>{new_btn}
</div>
<div class="card cal-card">
  <table class="cal-tbl">
    <thead><tr><th>窑炉</th>{head}</tr></thead>
    <tbody>{''.join(body_rows)}</tbody>
  </table>
  <p class="muted small">同一窑炉时段不能重叠；已点火批次按实际烧制+冷却时段展示。</p>
</div>"""
    return layout("窑炉日历", user, body, "/calendar")


def batch_new_page(options: dict, user: dict, msg: str = "") -> str:
    kiln_opts = "".join(f'<option value="{k["id"]}">{esc(k["name"])}</option>'
                        for k in options["kilns"])
    program_opts = "".join(
        f'<option value="{p["id"]}">{esc(p["name"])}（{"素烧" if p["kind"] == "bisque" else "釉烧"}）</option>'
        for p in options["programs"])
    default_start = (datetime.now() + timedelta(days=1)).replace(hour=18, minute=0,
                                                                 second=0, microsecond=0)
    default_end = default_start + timedelta(hours=16)
    notice = f'<div class="notice err">{esc(msg)}</div>' if msg else ""
    body = f"""
<h2 class="page-title">排期新批次</h2>
{notice}
<div class="card">
  <form method="post" action="/batches" class="form-grid">
    <label>批次名称<input name="name" required placeholder="如：一号窑·素烧·周五"></label>
    <label>窑炉<select name="kiln_id">{kiln_opts}</select></label>
    <label>烧制程序<select name="program_id">{program_opts}</select></label>
    <label>类型<select name="kind"><option value="bisque">素烧</option><option value="glaze">釉烧</option></select></label>
    <label>开始时间<input name="start" type="datetime-local" required
           value="{default_start.strftime('%Y-%m-%dT%H:%M')}"></label>
    <label>结束时间<input name="end" type="datetime-local" required
           value="{default_end.strftime('%Y-%m-%dT%H:%M')}"></label>
    <div class="form-actions"><button class="btn" type="submit">创建批次（教师权限）</button></div>
  </form>
  <p class="muted small">提示：时段需覆盖烧制与冷却；与既有批次重叠会被拒绝。</p>
</div>"""
    return layout("排期新批次", user, body, "/calendar")


# ---------------------------------------------------------------- 页面：批次详情


def batch_detail_page(detail: dict, loadable: list[dict], programs: list[dict],
                      current: dict | None, user: dict, msg: str = "") -> str:
    b, kiln, program = detail["batch"], detail["kiln"], detail["program"]
    items = detail["items"]
    is_staff = user["role"] in ("admin", "teacher")
    is_admin = user["role"] == "admin"
    scheduled = b["status"] == "scheduled"

    # 头部信息
    head_rows = f"""
      <tr><th>窑炉</th><td>{esc(kiln['name'])}（{kiln['shelf_count']} 层 · 层净高 {kiln['shelf_clearance_cm']:.0f}cm）</td></tr>
      <tr><th>程序</th><td>{esc(program['name'])} · {'素烧' if b['kind'] == 'bisque' else '釉烧'}</td></tr>
      <tr><th>排期</th><td>{fmt(b['scheduled_start'])} ~ {fmt(b['scheduled_end'])}</td></tr>
      <tr><th>点火</th><td>{fmt(b['ignited_at'])} {('· ' + esc(detail['igniter'])) if detail['igniter'] else ''}</td></tr>
      <tr><th>预计烧完</th><td>{fmt(b['firing_end_at'])}</td></tr>
      <tr><th>冷却完成</th><td>{fmt(b['cooled_at'])}</td></tr>
      <tr><th>开窑</th><td>{fmt(b['opened_at'])}{' <span class="badge b-bad">异常开窑</span>' if b['early_open'] else ''}</td></tr>"""

    # 操作按钮
    actions = []
    if scheduled and is_admin:
        actions.append(f"""
      <form method="post" action="/batches/{b['id']}/ignite" class="inline"
            onsubmit="return confirm('点火后批次与程序将锁定，确认点火？')">
        <button class="btn fire" type="submit">🔥 点火（管理员）</button></form>""")
    if b["status"] in ("firing", "cooling") and is_admin:
        actions.append(f"""
      <form method="post" action="/batches/{b['id']}/outage" class="inline"
            onsubmit="return confirm('上报停电中断？将留痕记录。')">
        <button class="btn warn" type="submit">⚡ 停电上报</button></form>""")
    if b["status"] == "interrupted" and is_admin:
        actions.append(f"""
      <form method="post" action="/batches/{b['id']}/restore" class="inline">
        <button class="btn" type="submit">🔌 恢复供电</button></form>""")
    if b["status"] == "cooled" and is_staff:
        actions.append(f"""
      <form method="post" action="/batches/{b['id']}/open" class="inline">
        <button class="btn" type="submit">开窑（已完全冷却）</button></form>""")
    if b["status"] in ("firing", "cooling", "interrupted") and is_admin:
        actions.append(f"""
      <form method="post" action="/batches/{b['id']}/open" class="inline"
            onsubmit="return confirm('窑炉尚未完全冷却！异常开窑将留痕，确认？')">
        <button class="btn danger" type="submit">⚠ 异常开窑（管理员）</button></form>""")
    if b["status"] == "opened" and is_staff:
        done = all(i["result"] for i in items)
        if not done:
            actions.append(f'<a class="btn" href="/batches/{b["id"]}/inventory">出窑清点</a>')

    # 温度监控
    monitor = ""
    if b["status"] in ("firing", "cooling", "interrupted") and current:
        cooling_line = ""
        if b["status"] == "cooling" and b["cooled_at"]:
            cooling_line = (f'<div class="cooling-timer" data-cooled-at="{esc(b["cooled_at"])}">'
                            f'冷却倒计时：<b>--</b></div>')
        monitor = f"""
<div class="card monitor-card">
  <h3>烧制监控</h3>
  <div class="monitor-flex">
    <div class="temp-big" data-temp-kiln="{kiln['id']}">
      <span class="temp-num">--</span><span class="temp-unit">°C</span>
      <span class="temp-phase"></span>
    </div>
    <div>{cooling_line}
      <div class="muted small">温度由模拟适配器提供，每 2 秒刷新</div>
    </div>
  </div>
</div>"""

    # 程序确认 + 阶梯曲线
    program_form = ""
    if scheduled and is_staff:
        opts = "".join(
            f'<option value="{p["id"]}"{" selected" if p["id"] == program["id"] else ""}>'
            f'{esc(p["name"])}</option>' for p in programs)
        program_form = f"""
    <form method="post" action="/batches/{b['id']}/program" class="inline-flex">
      <select name="program_id">{opts}</select>
      <button class="btn sm" type="submit">确认程序</button>
      <span class="muted small">点火后程序锁定</span>
    </form>"""
    seg_rows = "".join(
        f'<tr><td>{i + 1}</td>'
        f'<td>{("升温至 " + str(s["target"]) + "°C（" + str(s["rate"]) + "°C/h）") if "rate" in s else ("保温 " + str(s["hold"]) + " 分钟")}</td></tr>'
        for i, s in enumerate(detail["segments"]))
    duration_h = domain.program_duration_minutes(detail["segments"]) / 60.0
    program_card = f"""
<div class="card">
  <h3>烧制程序确认</h3>
  {program_form}
  {program_curve_svg(detail['segments'], b, current)}
  <table class="tbl slim"><thead><tr><th>#</th><th>程序段（总时长约 {duration_h:.1f} 小时 + 冷却 {kiln['cooling_hours']:.0f} 小时）</th></tr></thead>
  <tbody>{seg_rows}</tbody></table>
</div>"""

    # 棚板排布
    shelves_html = []
    for shelf in range(1, kiln["shelf_count"] + 1):
        shelf_items = [i for i in items if i["shelf_no"] == shelf]
        legend_parts = []
        for i in shelf_items:
            label_warn = ('<span class="badge b-warn">标签脱落</span>'
                          if i["label_detached"] else "")
            remove_btn = ""
            if scheduled and is_staff:
                remove_btn = (
                    f'<form method="post" action="/batches/{b["id"]}/items/{i["item_id"]}/remove"'
                    f' class="inline"><button class="btn ghost xs" type="submit">取出</button></form>')
            legend_parts.append(
                f'<li>{glaze_dot(i["color_hex"], i["glaze_name"])} <b>{esc(i["code"])}</b>'
                f'（{esc(i["anon_code"])} · {i["width_cm"]:.0f}×{i["depth_cm"]:.0f}'
                f'×{i["height_cm"]:.0f}cm）{label_warn}{remove_btn}</li>')
        legend = "".join(legend_parts)
        shelves_html.append(f"""
    <div class="shelf-block">
      <h4>第 {shelf} 层 <span class="muted small">{len(shelf_items)}/{kiln['shelf_slots']} 工位</span></h4>
      {shelf_layout_svg(kiln, items, shelf)}
      <ul class="shelf-legend">{legend or '<li class="muted">空层</li>'}</ul>
    </div>""")
    load_form = ""
    if scheduled and is_staff:
        work_opts = "".join(
            f'<option value="{w["id"]}">{esc(w["code"])} · {esc(w["glaze_name"])} · '
            f'{w["height_cm"]:.0f}cm高</option>'
            for w in loadable)
        shelf_opts = "".join(f'<option value="{s}">第 {s} 层</option>'
                             for s in range(1, kiln["shelf_count"] + 1))
        checkboxes = "".join(
            f'<label class="chk"><input type="checkbox" name="work_ids" value="{w["id"]}">'
            f' {esc(w["code"])}（{esc(w["glaze_name"])}，{w["height_cm"]:.0f}cm）</label>'
            for w in loadable)
        load_form = f"""
    <div class="load-panel">
      <h4>装窑 <span class="muted small">按尺寸与釉料相容性分配棚板</span></h4>
      <form method="post" action="/batches/{b['id']}/items" class="inline-flex">
        <select name="work_id">{work_opts or '<option value="">（无可装窑作品）</option>'}</select>
        <select name="shelf_no">{shelf_opts}</select>
        <button class="btn sm" type="submit">装入指定层</button>
      </form>
      <form method="post" action="/batches/{b['id']}/auto" class="auto-form">
        <div class="chk-list">{checkboxes or '<span class="muted">暂无可装窑作品</span>'}</div>
        <button class="btn sm ghost" type="submit">自动分配选中作品</button>
      </form>
    </div>"""
    shelves_card = f"""
<div class="card">
  <h3>棚板排布（圆形层位俯视）</h3>
  {load_form}
  <div class="shelf-grid">{''.join(shelves_html)}</div>
</div>"""

    # 照片
    photos = "".join(
        f'<figure class="photo"><img src="/photos/{esc(p["filename"])}" alt="装窑照片">'
        f'<figcaption>装窑 · {fmt(p["created_at"])}</figcaption></figure>'
        for p in detail["photos"])
    upload = ""
    if is_staff:
        upload = f"""
    <div class="inline-flex"><input type="file" id="photo-file" accept="image/*">
      <button class="btn sm" data-upload-photo kind="loading" batch-id="{b['id']}">上传装窑照片</button></div>"""
    photos_card = f"""
<div class="card"><h3>装窑照片</h3>
  <div class="photo-grid">{photos or '<p class="muted">暂无照片</p>'}</div>{upload}</div>"""

    # 出窑结果
    result_card = ""
    if b["status"] == "opened":
        rows = "".join(
            f'<tr><td><a href="/works/{i["work_id"]}"><b>{esc(i["code"])}</b></a></td>'
            f'<td>第 {i["shelf_no"]} 层</td>'
            f'<td>{esc({"ok": "完好", "cracked": "裂损", "missing": "少件"}.get(i["result"], "未清点"))}'
            f'{"（" + esc(i["result_note"]) + "）" if i["result_note"] else ""}</td></tr>'
            for i in items)
        result_card = f"""
<div class="card"><h3>出窑结果</h3>
  <table class="tbl"><thead><tr><th>作品</th><th>位置</th><th>结果</th></tr></thead>
  <tbody>{rows}</tbody></table></div>"""

    incident_rows = "".join(
        f'<tr><td>{incident_badge(i["type"])}</td><td>{esc(i["detail"])}</td>'
        f'<td class="muted">{esc(i["actor_name"] or "—")} · {fmt(i["created_at"])}</td></tr>'
        for i in detail["incidents"])
    notice = f'<div class="notice">{esc(msg)}</div>' if msg else ""
    body = f"""
<h2 class="page-title">{esc(b['name'])} {batch_badge(b['status'])}</h2>
{notice}
<div class="actions">{''.join(actions)}</div>
{monitor}
<div class="two-col">
  <div class="card"><h3>批次信息</h3><table class="kv">{head_rows}</table>
    <p class="muted small">创建：{esc(detail['creator'])} · {fmt(b['created_at'])}</p></div>
  {program_card}
</div>
{shelves_card}
{result_card}
{photos_card}
<div class="card"><h3>本批次异常留痕</h3>
  <table class="tbl"><tbody>{incident_rows or '<tr><td class="muted">无</td></tr>'}</tbody></table></div>"""
    return layout(b["name"], user, body, "/calendar")


# ---------------------------------------------------------------- 页面：出窑清点


def inventory_page(detail: dict, user: dict) -> str:
    b = detail["batch"]
    rows = []
    for i in detail["items"]:
        current = i["result"] or ""
        opts = "".join(
            f'<option value="{v}"{" selected" if current == v else ""}>{label}</option>'
            for v, label in [("ok", "完好"), ("cracked", "裂损"), ("missing", "少件")])
        rows.append(f"""
    <tr>
      <td><b>{esc(i['code'])}</b>（{esc(i['anon_code'])}）</td>
      <td>第 {i['shelf_no']} 层 · 位 {i['slot_no']}</td>
      <td>{glaze_dot(i['color_hex'], i['glaze_name'])}</td>
      <td><select name="result_{i['item_id']}">{opts}</select></td>
      <td><input name="note_{i['item_id']}" placeholder="备注（裂纹位置等）"
           value="{esc(i['result_note'])}"></td>
    </tr>""")
    body = f"""
<h2 class="page-title">出窑清点 · {esc(b['name'])}</h2>
<div class="card">
  <p class="muted">逐件登记出窑结果；裂损与少件将自动留痕，裂损作品可随后创建补烧。</p>
  <form method="post" action="/batches/{b['id']}/inventory">
    <table class="tbl">
      <thead><tr><th>作品</th><th>位置</th><th>釉色</th><th>结果</th><th>备注</th></tr></thead>
      <tbody>{''.join(rows)}</tbody>
    </table>
    <div class="form-actions"><button class="btn" type="submit">提交清点结果</button></div>
  </form>
</div>"""
    return layout("出窑清点", user, body)


# ---------------------------------------------------------------- 页面：异常留痕 / 补烧追踪


def incidents_page(incidents: list[dict], user: dict) -> str:
    def work_cell(i):
        if i["work_id"] and i["work_code"]:
            return f'<a href="/works/{i["work_id"]}">{esc(i["work_code"])}</a>'
        return "—"

    rows = "".join(
        f'<tr><td>{incident_badge(i["type"])}</td>'
        f'<td>{work_cell(i)}</td>'
        f'<td>{esc(i["batch_name"] or "—")}</td>'
        f'<td>{esc(i["detail"])}</td>'
        f'<td class="muted">{esc(i["actor_name"] or "系统")} · {fmt(i["created_at"])}</td></tr>'
        for i in incidents)
    body = f"""
<h2 class="page-title">异常留痕</h2>
<p class="muted">标签脱落、干燥不足、釉料相冲、装载超高、停电中断、异常开窑、裂损、少件，全部留痕可查。</p>
<div class="card">
  <table class="tbl">
    <thead><tr><th>类型</th><th>作品</th><th>批次</th><th>详情</th><th>记录</th></tr></thead>
    <tbody>{rows or '<tr><td colspan="5" class="muted">暂无异常</td></tr>'}</tbody>
  </table>
</div>"""
    return layout("异常留痕", user, body, "/incidents")


def refires_page(refires: list[dict], user: dict) -> str:
    status_label = {"pending": "待安排", "scheduled": "已排入批次", "done": "补烧完成"}
    rows = "".join(
        f'<tr><td><b>{esc(r["work_code"])}</b></td>'
        f'<td>{esc(r["reason"])}</td>'
        f'<td>{esc(r["source_batch_name"])}</td>'
        f'<td>{esc(r["new_batch_name"] or "—")}</td>'
        f'<td><span class="badge b-warn">{esc(status_label.get(r["status"], r["status"]))}</span></td>'
        f'<td class="muted">{esc(r["creator_name"])} · {fmt(r["created_at"])}</td></tr>'
        for r in refires)
    body = f"""
<h2 class="page-title">补烧追踪</h2>
<p class="muted">补烧必须引用原作品与失败原因；裂损作品在作品详情页创建补烧后，可排入新批次。</p>
<div class="card">
  <table class="tbl">
    <thead><tr><th>作品</th><th>失败原因</th><th>原批次</th><th>补烧批次</th><th>状态</th><th>创建</th></tr></thead>
    <tbody>{rows or '<tr><td colspan="6" class="muted">暂无补烧记录</td></tr>'}</tbody>
  </table>
</div>"""
    return layout("补烧追踪", user, body, "/refires")


# ---------------------------------------------------------------- 页面：学生端


def student_page(view: dict, user: dict) -> str:
    stage_labels = ["自然干燥", "干燥合格", "装窑排烧", "烧制冷却", "出窑"]
    cards = []
    for w in view["works"]:
        if w["status"] in ("completed",):
            idx = 4
        elif w["status"] in ("damaged", "missing", "refire_pending"):
            idx = 4
        else:
            order = ["drying", "dry_qualified", "scheduled", "firing"]
            idx = order.index(w["status"]) if w["status"] in order else 0
        timeline = "".join(
            f'<li class="{"done" if i <= idx else ""}"><i></i>{label}</li>'
            for i, label in enumerate(stage_labels))
        photos = "".join(
            f'<figure class="photo"><img src="/photos/{esc(p["filename"])}" alt="成品照片"></figure>'
            for p in w["photos"])
        result_note = ""
        if w["status"] == "damaged":
            result_note = '<p class="muted">作品在烧制中出现裂损，老师已安排补烧。</p>'
        elif w["status"] == "refire_pending":
            result_note = '<p class="muted">作品正在等待补烧。</p>'
        elif w["status"] == "missing":
            result_note = '<p class="muted">作品在清点时未找到，老师会跟进处理。</p>'
        cards.append(f"""
  <div class="card work-card">
    <h3>{esc(w['code'])} {work_badge(w['status'])}</h3>
    <p>{glaze_dot(w['color_hex'], w['glaze_name'])} · {esc(w['clay_name'])}
       · {w['width_cm']:.0f}×{w['depth_cm']:.0f}×{w['height_cm']:.0f}cm</p>
    <ol class="timeline">{timeline}</ol>
    {result_note}
    <div class="photo-grid">{photos}</div>
  </div>""")
    body = f"""
<h2 class="page-title">我的作品 · {esc(view['student']['anon_code'])}（{esc(view['class_name'])}）</h2>
<p class="muted">这里可以看到每件作品的进度和成品照片。</p>
<div class="work-grid">{''.join(cards) or '<div class="card">还没有作品</div>'}</div>"""
    return layout("我的作品", user, body, "/student")
