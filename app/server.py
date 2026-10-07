"""零依赖 HTTP 服务：页面、健康响应与验证接口。

环境变量：
  HOST  监听地址（默认 0.0.0.0）
  PORT  监听端口（默认 8080，可由 Compose 配置宿主端口）
"""

from __future__ import annotations

import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .service import verify_spec
from .webui import PAGE_HTML

__all__ = ["build_handler", "main"]


def build_handler():
    class Handler(BaseHTTPRequestHandler):
        server_version = "EqVerify/1.0"

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload: dict) -> None:
            self._send(
                status,
                json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
                "application/json; charset=utf-8",
            )

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/health":
                self._json(
                    HTTPStatus.OK,
                    {"status": "ok", "service": "equivalence-verifier"},
                )
                return
            if path in ("/", "/index.html"):
                self._send(
                    HTTPStatus.OK,
                    PAGE_HTML.encode("utf-8"),
                    "text/html; charset=utf-8",
                )
                return
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found", "path": path})

        def do_POST(self) -> None:
            path = self.path.split("?", 1)[0]
            if path != "/api/verify":
                self._json(HTTPStatus.NOT_FOUND, {"error": "not found", "path": path})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length > 0 else b"{}"
                payload = json.loads(raw.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("请求体必须是 JSON 对象")
            except (ValueError, UnicodeDecodeError) as exc:
                self._json(
                    HTTPStatus.BAD_REQUEST,
                    {"status": "invalid",
                     "errors": [{"scope": "request", "message": f"请求体无法解析：{exc}"}]},
                )
                return
            self._json(HTTPStatus.OK, verify_spec(payload))

        def log_message(self, fmt: str, *args) -> None:  # noqa: A003
            if os.environ.get("QUIET"):
                return
            super().log_message(fmt, *args)

    return Handler


def main() -> None:
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8080"))
    httpd = ThreadingHTTPServer((host, port), build_handler())
    print(f"equivalence-verifier listening on http://{host}:{port}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
