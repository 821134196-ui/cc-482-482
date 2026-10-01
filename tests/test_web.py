"""Web 层冒烟测试：登录、页面可达、权限边界、温度 API。"""
import http.client
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from base import ServiceTestCase
from pottery.web import serve

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "pottery", "static")


class TestWeb(ServiceTestCase):
    def setUp(self):
        super().setUp()
        self.server = serve(self.svc, STATIC_DIR, port=0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def _req(self, method, path, body=None, cookie=None, ctype=None):
        conn = http.client.HTTPConnection("localhost", self.port, timeout=5)
        headers = {}
        if cookie:
            headers["Cookie"] = cookie
        if body is not None and ctype:
            headers["Content-Type"] = ctype
        conn.request(method, path, body=body, headers=headers)
        resp = conn.getresponse()
        data = resp.read()
        conn.close()
        return resp.status, dict(resp.getheaders()), data

    def _login(self, user_id):
        status, headers, _ = self._req(
            "POST", "/login", body=f"user_id={user_id}",
            ctype="application/x-www-form-urlencoded")
        self.assertEqual(status, 303)
        return headers["Set-Cookie"].split(";")[0]

    def test_login_and_pages(self):
        # 未登录重定向到登录页
        status, headers, _ = self._req("GET", "/")
        self.assertEqual(status, 303)
        self.assertEqual(headers["Location"], "/login")
        # 管理员登录后各页面可达
        admin = self._login(1)
        for path in ["/", "/works", "/drying", "/calendar", "/incidents", "/refires"]:
            status, _, body = self._req("GET", path, cookie=admin)
            self.assertEqual(status, 200, path)
            self.assertIn("陶艺".encode("utf-8"), body)

    def test_student_boundary(self):
        student = self._login(3)
        status, _, _ = self._req("GET", "/student", cookie=student)
        self.assertEqual(status, 200)
        status, _, _ = self._req("GET", "/works", cookie=student)
        self.assertEqual(status, 403)
        status, _, _ = self._req("POST", "/drying/confirm", body="work_id=1",
                                 cookie=student, ctype="application/x-www-form-urlencoded")
        self.assertEqual(status, 403)

    def test_teacher_cannot_ignite_over_http(self):
        work = self.qualify(self.make_work())
        batch = self.make_batch()
        self.svc.add_work_to_batch(self.teacher_id, batch, work, 1)
        teacher = self._login(2)
        status, _, body = self._req("POST", f"/batches/{batch}/ignite", cookie=teacher)
        self.assertEqual(status, 403)
        admin = self._login(1)
        status, headers, _ = self._req("POST", f"/batches/{batch}/ignite", cookie=admin)
        self.assertEqual(status, 303)

    def test_temp_api(self):
        admin = self._login(1)
        status, _, body = self._req("GET", "/api/kiln/1/temp", cookie=admin)
        self.assertEqual(status, 200)
        self.assertIn(b'"temp"', body)


if __name__ == "__main__":
    import unittest
    unittest.main()
