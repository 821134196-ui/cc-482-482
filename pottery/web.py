"""HTTP 层：基于标准库 http.server 的路由、会话与权限控制。"""
from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime, timedelta
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

from . import views
from .kiln_adapter import SimulatedKilnAdapter
from .services import (
    STAFF,
    DomainError,
    NotFound,
    PermissionDenied,
    PotteryService,
)

MAX_UPLOAD = 8 * 1024 * 1024  # 8MB


class Request:
    def __init__(self, handler: "Handler"):
        self.handler = handler
        parsed = urlparse(handler.path)
        self.path = parsed.path
        self.query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        self.method = handler.command
        self._body = None
        self._form = None
        self._user = None

    def raw_body(self) -> bytes:
        if self._body is None:
            length = int(self.handler.headers.get("Content-Length") or 0)
            self._body = self.handler.rfile.read(length) if length else b""
        return self._body

    @property
    def form(self) -> dict:
        if self._form is None:
            ctype = self.handler.headers.get("Content-Type", "")
            if "application/x-www-form-urlencoded" in ctype:
                self._form = {k: v[0] for k, v in
                              parse_qs(self.raw_body().decode("utf-8")).items()}
            else:
                self._form = {}
        return self._form

    def form_list(self, key: str) -> list[str]:
        return parse_qs(self.raw_body().decode("utf-8")).get(key, [])

    @property
    def user(self) -> dict | None:
        if self._user is None:
            self._user = self.handler.app.current_user(self)
        return self._user


class Response:
    def __init__(self, body=b"", status=200, content_type="text/html; charset=utf-8",
                 headers=None):
        self.body = body.encode("utf-8") if isinstance(body, str) else body
        self.status = status
        self.content_type = content_type
        self.headers = headers or {}


def redirect(location: str) -> Response:
    # Location 头须为 latin-1：对中文等非 ASCII 字符做 URL 编码
    safe_location = quote(location, safe="/:?=&%#.+_-")
    return Response(b"", 303, headers={"Location": safe_location})


class LoginRequired(Exception):
    """未登录：重定向到登录页。"""


class App:
    """路由与依赖装配。"""

    def __init__(self, service: PotteryService, static_dir: str):
        self.svc = service
        self.adapter = SimulatedKilnAdapter(service)
        self.static_dir = static_dir
        self.sessions: dict[str, int] = {}  # token -> user_id（进程内会话）
        self.routes = []
        self._register()

    # ------------------------------------------------------------ 会话
    def current_user(self, req: Request) -> dict | None:
        cookie = cookies.SimpleCookie(req.handler.headers.get("Cookie"))
        morsel = cookie.get("sid")
        if not morsel:
            return None
        user_id = self.sessions.get(morsel.value)
        if user_id is None:
            return None
        row = self.svc._one("SELECT * FROM users WHERE id = ?", (user_id,))
        return dict(row) if row else None

    def login(self, user_id: int) -> str:
        token = secrets.token_hex(16)
        self.sessions[token] = user_id
        return token

    # ------------------------------------------------------------ 路由
    def route(self, method: str, pattern: str):
        def deco(fn):
            self.routes.append((method, re.compile(f"^{pattern}$"), fn))
            return fn
        return deco

    def _register(self):
        R = self.route

        @R("GET", r"/")
        def home(req):
            user = self._require_login(req)
            if user["role"] == "student":
                return redirect("/student")
            return views.dashboard(self.svc.kiln_cards(), self.svc.counts(),
                                   self.svc.recent_incidents(), user)

        # ---- 登录 ----
        @R("GET", r"/login")
        def login_page(req):
            return views.login_page(self.svc.options()["users"], req.user)

        @R("POST", r"/login")
        def do_login(req):
            user_id = int(req.form.get("user_id", "0"))
            row = self.svc._one("SELECT * FROM users WHERE id = ?", (user_id,))
            if row is None:
                raise NotFound("用户不存在")
            token = self.login(user_id)
            resp = redirect("/student" if row["role"] == "student" else "/")
            resp.headers["Set-Cookie"] = f"sid={token}; Path=/; HttpOnly; SameSite=Lax"
            return resp

        @R("GET", r"/logout")
        def logout(req):
            cookie = cookies.SimpleCookie(req.handler.headers.get("Cookie"))
            morsel = cookie.get("sid")
            if morsel:
                self.sessions.pop(morsel.value, None)
            resp = redirect("/login")
            resp.headers["Set-Cookie"] = "sid=; Path=/; Max-Age=0"
            return resp

        # ---- 作品 ----
        @R("GET", r"/works")
        def works(req):
            user = self._require_staff(req)
            return views.works_page(self.svc.list_works(), self.svc.options(), user,
                                    req.query.get("msg", ""))

        @R("POST", r"/works")
        def create_work(req):
            user = self._require_staff(req)
            f = req.form
            self.svc.register_work(user["id"], int(f["student_id"]), int(f["clay_id"]),
                                   int(f["glaze_id"]), f["width"], f["depth"], f["height"],
                                   f.get("drying_hours", "48"))
            return redirect("/works?msg=登记成功，作品已进入自然干燥")

        @R("GET", r"/works/(\d+)")
        def work_detail(req, work_id):
            user = self._require_staff(req)
            return views.work_detail_page(self.svc.work_chain(int(work_id)), user,
                                          req.query.get("msg", ""))

        @R("POST", r"/works/(\d+)/label")
        def work_label(req, work_id):
            user = self._require_staff(req)
            self.svc.report_label_detached(user["id"], int(work_id))
            return redirect(f"/works/{work_id}?msg=已标记标签脱落并留痕")

        @R("POST", r"/works/(\d+)/refire")
        def work_refire(req, work_id):
            user = self._require_staff(req)
            self.svc.create_refire(user["id"], int(work_id), req.form.get("reason", ""))
            return redirect(f"/works/{work_id}?msg=补烧已创建，可排入新批次")

        # ---- 干燥队列 ----
        @R("GET", r"/drying")
        def drying(req):
            user = self._require_staff(req)
            return views.drying_page(self.svc.drying_queue(), user, req.query.get("msg", ""))

        @R("POST", r"/drying/confirm")
        def drying_confirm(req):
            user = self._require_staff(req)
            self.svc.confirm_drying(user["id"], int(req.form["work_id"]))
            return redirect("/drying?msg=已确认干燥合格")

        # ---- 日历与批次 ----
        @R("GET", r"/calendar")
        def calendar(req):
            user = self._require_staff(req)
            offset = int(req.query.get("w", "0"))
            today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            week_start = today - timedelta(days=today.weekday()) + timedelta(weeks=offset)
            week_end = week_start + timedelta(days=7)
            return views.calendar_page(self.svc.options()["kilns"],
                                       self.svc.calendar_batches(week_start, week_end),
                                       week_start, offset, user)

        @R("GET", r"/batches/new")
        def batch_new(req):
            user = self._require_staff(req)
            return views.batch_new_page(self.svc.options(), user)

        @R("POST", r"/batches")
        def batch_create(req):
            user = self._require_staff(req)
            f = req.form
            start = datetime.fromisoformat(f["start"])
            end = datetime.fromisoformat(f["end"])
            batch_id = self.svc.schedule_batch(user["id"], int(f["kiln_id"]),
                                               int(f["program_id"]), f["name"],
                                               f["kind"], start, end)
            return redirect(f"/batches/{batch_id}")

        @R("GET", r"/batches/(\d+)")
        def batch_detail(req, batch_id):
            user = self._require_staff(req)
            detail = self.svc.batch_detail(int(batch_id))
            current = None
            if detail["batch"]["status"] in ("firing", "cooling", "interrupted"):
                current = self.adapter.read(detail["kiln"]["id"])
            return views.batch_detail_page(detail, self.svc.loadable_works(),
                                           self.svc.options()["programs"], current, user,
                                           req.query.get("msg", ""))

        @R("POST", r"/batches/(\d+)/program")
        def batch_program(req, batch_id):
            user = self._require_staff(req)
            self.svc.change_program(user["id"], int(batch_id), int(req.form["program_id"]))
            return redirect(f"/batches/{batch_id}?msg=程序已确认")

        @R("POST", r"/batches/(\d+)/items")
        def batch_add_item(req, batch_id):
            user = self._require_staff(req)
            self.svc.add_work_to_batch(user["id"], int(batch_id),
                                       int(req.form["work_id"]), int(req.form["shelf_no"]))
            return redirect(f"/batches/{batch_id}?msg=已装窑")

        @R("POST", r"/batches/(\d+)/auto")
        def batch_auto(req, batch_id):
            user = self._require_staff(req)
            work_ids = [int(x) for x in req.form_list("work_ids")]
            result = self.svc.auto_assign(user["id"], int(batch_id), work_ids)
            msg = f"自动分配：成功 {len(result['placed'])} 件"
            if result["failed"]:
                msg += "，失败 " + "、".join(f["code"] for f in result["failed"])
            return redirect(f"/batches/{batch_id}?msg={msg}")

        @R("POST", r"/batches/(\d+)/items/(\d+)/remove")
        def batch_remove_item(req, batch_id, item_id):
            user = self._require_staff(req)
            self.svc.remove_work_from_batch(user["id"], int(item_id))
            return redirect(f"/batches/{batch_id}?msg=已取出作品")

        @R("POST", r"/batches/(\d+)/ignite")
        def batch_ignite(req, batch_id):
            user = self._require_role(req, ("admin",))
            self.svc.ignite(user["id"], int(batch_id))
            return redirect(f"/batches/{batch_id}?msg=已点火，批次与程序锁定")

        @R("POST", r"/batches/(\d+)/outage")
        def batch_outage(req, batch_id):
            user = self._require_role(req, ("admin",))
            self.svc.report_power_outage(user["id"], int(batch_id))
            return redirect(f"/batches/{batch_id}?msg=已记录停电中断")

        @R("POST", r"/batches/(\d+)/restore")
        def batch_restore(req, batch_id):
            user = self._require_role(req, ("admin",))
            self.svc.restore_power(user["id"], int(batch_id))
            return redirect(f"/batches/{batch_id}?msg=供电恢复，时点已顺延")

        @R("POST", r"/batches/(\d+)/open")
        def batch_open(req, batch_id):
            user = self._require_staff(req)
            self.svc.open_kiln(user["id"], int(batch_id))
            return redirect(f"/batches/{batch_id}?msg=已开窑，请进行出窑清点")

        @R("GET", r"/batches/(\d+)/inventory")
        def inventory_page(req, batch_id):
            user = self._require_staff(req)
            return views.inventory_page(self.svc.batch_detail(int(batch_id)), user)

        @R("POST", r"/batches/(\d+)/inventory")
        def inventory_save(req, batch_id):
            user = self._require_staff(req)
            detail = self.svc.batch_detail(int(batch_id))
            results = {}
            for item in detail["items"]:
                key = f"result_{item['item_id']}"
                if key in req.form:
                    results[item["item_id"]] = (req.form[key],
                                                req.form.get(f"note_{item['item_id']}", ""))
            self.svc.record_inventory(user["id"], int(batch_id), results)
            return redirect(f"/batches/{batch_id}?msg=出窑清点完成")

        # ---- 异常与补烧 ----
        @R("GET", r"/incidents")
        def incidents(req):
            user = self._require_staff(req)
            return views.incidents_page(self.svc.list_incidents(), user)

        @R("GET", r"/refires")
        def refires(req):
            user = self._require_staff(req)
            return views.refires_page(self.svc.list_refires(), user)

        # ---- 学生端 ----
        @R("GET", r"/student")
        def student(req):
            user = self._require_login(req)
            if user["role"] != "student":
                return redirect("/")
            return views.student_page(self.svc.student_view(user["id"]), user)

        # ---- 照片 ----
        @R("GET", r"/photos/([\w\.\-]+)")
        def photo(req, name):
            self._require_login(req)
            path = os.path.join(self.svc.photos_dir, name)
            if not os.path.isfile(path):
                raise NotFound("照片不存在")
            with open(path, "rb") as f:
                data = f.read()
            ctype = "image/svg+xml" if name.endswith(".svg") else "image/jpeg"
            if name.endswith(".png"):
                ctype = "image/png"
            return Response(data, 200, ctype)

        @R("POST", r"/photos/upload")
        def photo_upload(req):
            user = self._require_staff(req)
            q = req.query
            kind = q.get("kind", "loading")
            data = req.raw_body()
            if not data:
                raise DomainError("未收到照片数据")
            if len(data) > MAX_UPLOAD:
                raise DomainError("照片超过 8MB 限制")
            ext = os.path.splitext(q.get("filename", "photo.jpg"))[1].lower()
            if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg"):
                ext = ".jpg"
            photo_id = self.svc.attach_photo(
                user["id"], kind, "tmp",
                work_id=int(q["work_id"]) if q.get("work_id") else None,
                batch_id=int(q["batch_id"]) if q.get("batch_id") else None)
            filename = f"p{photo_id:05d}{ext}"
            with open(os.path.join(self.svc.photos_dir, filename), "wb") as f:
                f.write(data)
            self.svc.conn.execute("UPDATE photos SET filename = ? WHERE id = ?",
                                  (filename, photo_id))
            self.svc.conn.commit()
            return Response(json.dumps({"ok": True, "filename": filename}),
                            200, "application/json")

        # ---- API ----
        @R("GET", r"/api/kiln/(\d+)/temp")
        def kiln_temp(req, kiln_id):
            self._require_login(req)
            return Response(json.dumps(self.adapter.read(int(kiln_id)), ensure_ascii=False),
                            200, "application/json; charset=utf-8")

        @R("GET", r"/static/([\w\.\-]+)")
        def static(req, name):
            path = os.path.join(self.static_dir, name)
            if not os.path.isfile(path):
                raise NotFound("静态资源不存在")
            with open(path, "rb") as f:
                data = f.read()
            ctype = {"css": "text/css; charset=utf-8",
                     "js": "application/javascript; charset=utf-8"}.get(
                name.rsplit(".", 1)[-1], "application/octet-stream")
            return Response(data, 200, ctype)

    # ------------------------------------------------------------ 权限
    def _require_login(self, req: Request) -> dict:
        if req.user is None:
            raise LoginRequired()
        return req.user

    def _require_staff(self, req: Request) -> dict:
        user = self._require_login(req)
        if user["role"] not in STAFF:
            raise PermissionDenied("学生端仅可查看作品进度")
        return user

    def _require_role(self, req: Request, roles) -> dict:
        user = self._require_login(req)
        if user["role"] not in roles:
            raise PermissionDenied("该操作需要管理员权限")
        return user

    # ------------------------------------------------------------ 分发
    def dispatch(self, req: Request) -> Response:
        for method, pattern, fn in self.routes:
            if method != req.method:
                continue
            m = pattern.match(req.path)
            if m:
                result = fn(req, *m.groups())
                if isinstance(result, Response):
                    return result
                return Response(result)
        raise NotFound("页面不存在")


class Handler(BaseHTTPRequestHandler):
    app: App = None  # 由 serve() 注入

    server_version = "PotteryKiln/1.0"
    protocol_version = "HTTP/1.1"

    def _handle(self):
        req = Request(self)
        try:
            resp = self.app.dispatch(req)
        except LoginRequired:
            resp = redirect("/login")
        except PermissionDenied as e:
            resp = Response(views.error_page("权限不足", str(e), req.user), 403)
        except NotFound as e:
            resp = Response(views.error_page("未找到", str(e), req.user), 404)
        except DomainError as e:
            resp = Response(views.error_page("操作被拒绝", str(e), req.user), 400)
        except (ValueError, KeyError) as e:
            resp = Response(views.error_page("请求参数有误", str(e), req.user), 400)
        except Exception as e:  # noqa: BLE001
            resp = Response(views.error_page("服务器错误", f"{type(e).__name__}: {e}",
                                             req.user), 500)
        self.send_response(resp.status)
        self.send_header("Content-Type", resp.content_type)
        self.send_header("Content-Length", str(len(resp.body)))
        for k, v in resp.headers.items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(resp.body)

    do_GET = _handle
    do_POST = _handle

    def log_message(self, fmt, *args):  # 静默访问日志
        pass


def serve(service: PotteryService, static_dir: str, port: int = 8000):
    app = App(service, static_dir)
    Handler.app = app
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    return server
