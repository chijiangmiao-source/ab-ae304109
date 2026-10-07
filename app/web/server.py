"""基于标准库的 HTTP 服务：页面、健康响应与复核接口。

路由
----

``GET  /``            单页应用（静态 HTML）
``GET  /healthz``     健康检查，返回 ``{"status":"ok"}``
``POST /api/verify``  真实复核接口，请求/响应均为 JSON

宿主端口由环境变量配置：``HOST_PORT``（默认 ``8080``），
监听地址由 ``HOST_ADDR`` 配置（默认 ``0.0.0.0``）。
"""

from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict
from urllib.parse import urlparse

from ..engine import analyze

_HERE = os.path.dirname(os.path.abspath(__file__))
_STATIC_DIR = os.path.join(_HERE, "static")
_MAX_BODY = 1 << 20  # 1 MiB，输入规模很小。


class Handler(BaseHTTPRequestHandler):
    server_version = "RewriteVerifier/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        # 简洁、确定的访问日志。
        print(f"[http] {self.address_string()} - {fmt % args}")

    # ------------------------------------------------------------------
    def _send_json(self, payload: Dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=False).encode(
            "utf-8"
        )
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, filename: str, content_type: str) -> None:
        path = os.path.join(_STATIC_DIR, filename)
        try:
            with open(path, "rb") as fh:
                body = fh.read()
        except OSError:
            self._send_json({"error": "static asset missing"}, 500)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802 (BaseHTTPRequestHandler API)
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._send_static("index.html", "text/html; charset=utf-8")
            return
        if path in ("/healthz", "/health"):
            self._send_json({"status": "ok", "service": "rewrite-verifier"})
            return
        if path == "/app.js":
            self._send_static(
                "app.js", "application/javascript; charset=utf-8"
            )
            return
        if path == "/styles.css":
            self._send_static("styles.css", "text/css; charset=utf-8")
            return
        self._send_json({"error": "not found", "path": path}, 404)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path != "/api/verify":
            self._send_json({"error": "not found", "path": path}, 404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            self._send_json(
                {
                    "status": "invalid",
                    "status_text": "无效",
                    "issues": [
                        {"code": "empty_body", "message": "请求体为空"}
                    ],
                },
                400,
            )
            return
        if length > _MAX_BODY:
            self._send_json({"error": "payload too large"}, 413)
            return
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._send_json(
                {
                    "status": "invalid",
                    "status_text": "无效",
                    "issues": [
                        {
                            "code": "bad_json",
                            "message": f"请求体不是合法 JSON：{exc}",
                        }
                    ],
                },
                400,
            )
            return
        if not isinstance(payload, dict):
            self._send_json(
                {
                    "status": "invalid",
                    "status_text": "无效",
                    "issues": [
                        {"code": "bad_shape", "message": "请求体必须是 JSON 对象"}
                    ],
                },
                400,
            )
            return
        try:
            result = analyze(payload)
        except Exception as exc:  # pragma: no cover - 防御性
            self._send_json({"error": "internal", "detail": str(exc)}, 500)
            return
        self._send_json(result, 200)


def build_server(host: str, port: int) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def main() -> None:
    host = os.environ.get("HOST_ADDR", "0.0.0.0")
    port = int(os.environ.get("HOST_PORT", os.environ.get("PORT", "8080")))
    server = build_server(host, port)
    print(f"[http] rewrite-verifier listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # pragma: no cover
        pass
    finally:
        server.server_close()


if __name__ == "__main__":  # pragma: no cover
    main()
