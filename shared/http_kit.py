"""
togikaidrive-tools 共通HTTPハンドラ部品
==========================================
3ツールのHandlerクラスで文言まで同一だった`_send_json`/`_read_json_body`を
1箇所にまとめたmixin。`http.server.BaseHTTPRequestHandler`と多重継承して使う。

例:
    class Handler(JSONHandlerMixin, BaseHTTPRequestHandler):
        def do_GET(self):
            ...
"""
from __future__ import annotations

import json


class JSONHandlerMixin:
    def log_message(self, fmt, *args):
        pass  # 標準出力を静かに保つ

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        return json.loads(raw.decode("utf-8")) if raw else {}

    def _send_html(self, body_text: str) -> None:
        body = body_text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.end_headers()
        self.wfile.write(body)
