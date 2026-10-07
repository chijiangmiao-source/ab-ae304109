"""HTTP 层测试（unittest）：页面、健康检查、真实接口。"""

import json
import threading
import unittest
from http.client import HTTPConnection

from app.web.server import build_server


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.srv = build_server("127.0.0.1", 0)
        self.thread = threading.Thread(
            target=self.srv.serve_forever, daemon=True
        )
        self.thread.start()
        self.port = self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        self.thread.join(timeout=2)

    def _get(self, path):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    def _post(self, payload):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(
            "POST",
            "/api/verify",
            body=json.dumps(payload, ensure_ascii=False),
            headers={"Content-Type": "application/json"},
        )
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        conn.close()
        return resp.status, data

    def test_index_page(self):
        status, body = self._get("/")
        self.assertEqual(status, 200)
        self.assertIn("控制表达式", body.decode("utf-8"))

    def test_static_assets(self):
        for path in ("app.js", "styles.css"):
            status, body = self._get("/" + path)
            self.assertEqual(status, 200)
            self.assertTrue(body)

    def test_healthz(self):
        status, body = self._get("/healthz")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["status"], "ok")

    def test_verify_equivalent(self):
        status, data = self._post(
            {
                "left": "f(add(a,b))",
                "right": "f(add(b,a))",
                "rules": ["add(x,y) = add(y,x)"],
            }
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "equivalent")
        self.assertTrue(data["proof"])

    def test_verify_not_equivalent(self):
        status, data = self._post({"left": "a", "right": "b", "rules": []})
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "not_equivalent")
        self.assertIsNone(data["proof"])
        self.assertTrue(data["classes"])

    def test_verify_unknown(self):
        status, data = self._post(
            {
                "left": "a",
                "right": "g(b)",
                "rules": ["x = d(f(x))"],
                "max_nodes": 80,
            }
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "unknown")
        self.assertTrue(data["limit_reason"])

    def test_verify_invalid(self):
        status, data = self._post(
            {"left": "f(a", "right": "b", "rules": []}
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["status"], "invalid")
        self.assertIsNone(data["proof"])

    def test_bad_json(self):
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("POST", "/api/verify", body="{not-json")
        resp = conn.getresponse()
        status = resp.status
        conn.close()
        self.assertEqual(status, 400)

    def test_404(self):
        status, _ = self._get("/nope")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
