#!/usr/bin/env python3
"""
アノテーションツール ランチャー
================================
`togikaidrive-dev/annotation_training_d2j/main.py`(画像アノテーション・
学習管理用の既存PyQt5デスクトップアプリ)を、ブラウザから起動するための
薄いランチャーツール。

背景:
    annotation_training_d2j は29,000行超のPyQt5デスクトップアプリで、
    Web機能を一切持たない(mlflow uiをサブプロセス起動する以外にHTTPサーバーの
    仕組みが無い)。他の3ツールのようにportalへタブ埋め込みで統合するのは
    現実的ではないため、本ツールでは中身を一切変更せず、サブプロセスとして
    起動するボタンだけを提供する。

使い方:
    python3 server.py
    → ブラウザで http://localhost:8902 を開く
"""
from __future__ import annotations

import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8902
HERE = Path(__file__).resolve().parent
TOOLS_ROOT = HERE.parent  # lab/ (兄弟ツールとshared/がある場所)
REPO_ROOT = TOOLS_ROOT.parent  # ト技会-minicar/ (togikaidrive-dev/ がある場所)

# ポータル(togikaidrive-portal)がタブとして埋め込む際に使うメタ情報
PANEL_ID = "annotation_launcher"
PANEL_TITLE = "アノテーションツール"
PANEL_ICON = "🖼️"

sys.path.insert(0, str(TOOLS_ROOT))
from shared import ui_kit  # noqa: E402
from shared import app_launcher  # noqa: E402
from shared.http_kit import JSONHandlerMixin  # noqa: E402

PALETTE = ui_kit.PALETTE
_html_escape = ui_kit.html_escape


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
def render_page() -> str:
    available = app_launcher.annotation_tool_available()
    status = app_launcher.launch_status()
    session = app_launcher.read_session_summary()
    return (
        HTML_SHELL
        .replace("__AVAILABLE__", "true" if available else "false")
        .replace("__TOOL_PATH__", _html_escape(str(app_launcher.ANNOTATION_TOOL_MAIN)))
        .replace("__STATUS_RUNNING__", "true" if status["running"] else "false")
        .replace("__STATUS_PID__", str(status["pid"] or ""))
        .replace("__SESSION_INFO__", _html_escape(
            f"最終更新: {session['mtime']}" if session else "情報なし"
        ))
    )


HTML_SHELL = f'''<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>アノテーションツール ランチャー</title>
<style>
  :root {{
    --navy: {PALETTE["navy"]}; --steel: {PALETTE["steel"]}; --steel-soft: {PALETTE["steel_soft"]};
    --cyan: {PALETTE["cyan"]}; --orange: {PALETTE["orange"]}; --card-bg: {PALETTE["card_bg"]};
    --text-dark: {PALETTE["text_dark"]}; --muted: {PALETTE["muted"]}; --orange-tint: {PALETTE["orange_tint"]};
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: #F7F8FB; color: var(--text-dark);
    font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Yu Gothic", "Segoe UI", sans-serif;
    padding-bottom: 2rem;
  }}
  header {{ background: var(--navy); color: #fff; padding: 1.4rem 1.5rem; }}
  header .eyebrow {{ color: var(--cyan); font-size: 0.75rem; font-weight: 700; letter-spacing: 0.12em; }}
  header h1 {{ margin: 0.3rem 0 0.4rem; font-size: 1.4rem; }}
  header p {{ margin: 0; color: #B9C0D4; font-size: 0.8rem; }}

  main {{ max-width: 700px; margin: 1.2rem auto 0; padding: 0 1.2rem; display: flex; flex-direction: column; gap: 1.1rem; }}
  .card {{ background: #fff; border-radius: 16px; box-shadow: 0 8px 24px rgba(16,19,26,0.08); padding: 1.4rem 1.5rem; }}
  .card h2 {{ margin: 0 0 0.6rem; font-size: 1.05rem; }}
  .card .sub {{ margin: 0 0 1rem; color: var(--muted); font-size: 0.85rem; line-height: 1.6; }}

  button.primary {{
    background: var(--orange); color: #fff; border: none; padding: 0.8rem 1.6rem; border-radius: 999px;
    font-size: 1rem; font-weight: 700; cursor: pointer;
  }}
  button.primary:disabled {{ opacity: 0.5; cursor: default; }}

  .status-row {{ display: flex; align-items: center; gap: 0.6rem; margin-top: 1rem; font-size: 0.85rem; }}
  .status-dot {{ width: 10px; height: 10px; border-radius: 50%; background: var(--muted); }}
  .status-dot.running {{ background: #0F5132; }}

  table.info {{ width: 100%; border-collapse: collapse; font-size: 0.82rem; margin-top: 0.6rem; }}
  table.info td {{ padding: 0.3rem 0.2rem; border-top: 1px solid #EEF0F5; }}
  table.info td:first-child {{ color: var(--muted); width: 40%; }}

  #toast {{
    position: fixed; top: 1rem; left: 50%; transform: translateX(-50%) translateY(-140%);
    background: var(--navy); color: #fff; padding: 0.7rem 1.2rem; border-radius: 10px;
    font-size: 0.85rem; transition: transform 0.25s ease; z-index: 10; max-width: 90vw;
  }}
  #toast.show {{ transform: translateX(-50%) translateY(0); }}
  #toast.error {{ background: var(--orange); }}
</style>
</head>
<body>
<header>
  <div class="eyebrow">TOGIKAIDRIVE · ANNOTATION</div>
  <h1>🖼️ アノテーションツール</h1>
  <p>画像アノテーション・学習管理の既存デスクトップアプリを起動します。</p>
</header>
<div id="toast"></div>
<main>
  <div class="card">
    <h2>▶️ 起動</h2>
    <p class="sub">
      annotation_training_d2j (main.py) をサブプロセスとして起動します。
      画像アノテーション、Google Colabへのデータ転送・学習済みモデルの取り込みは
      起動後のアプリ内(Cloudメニュー)で行ってください。<br>
      対象: __TOOL_PATH__
    </p>
    <button class="primary" id="annot-launch-btn" onclick="annotLaunchTool()">アノテーションツールを起動</button>
    <div class="status-row">
      <span class="status-dot" id="annot-status-dot"></span>
      <span id="annot-status-text">状態を確認中...</span>
    </div>
  </div>

  <div class="card">
    <h2>ℹ️ セッション情報(参考)</h2>
    <table class="info">
      <tr><td>最終セッション</td><td id="annot-session-info">__SESSION_INFO__</td></tr>
    </table>
  </div>
</main>
<script>
const ANNOT_AVAILABLE = __AVAILABLE__;
let ANNOT_RUNNING = __STATUS_RUNNING__;
let ANNOT_PID = "__STATUS_PID__";

function showToast(msg, isError) {{
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = isError ? 'show error' : 'show';
  setTimeout(() => {{ t.className = ''; }}, 3200);
}}

function annotRenderStatus() {{
  const dot = document.getElementById('annot-status-dot');
  const text = document.getElementById('annot-status-text');
  const btn = document.getElementById('annot-launch-btn');
  if (!ANNOT_AVAILABLE) {{
    text.textContent = 'アノテーションツールが見つかりません';
    btn.disabled = true;
    return;
  }}
  if (ANNOT_RUNNING) {{
    dot.classList.add('running');
    text.textContent = `起動中 (pid ${{ANNOT_PID}})`;
  }} else {{
    dot.classList.remove('running');
    text.textContent = '停止中';
  }}
}}
annotRenderStatus();

async function annotLaunchTool() {{
  try {{
    const res = await fetch('/annotation/launch', {{method: 'POST'}});
    const data = await res.json();
    if (!data.ok) {{ showToast(data.message || '起動に失敗しました', true); return; }}
    ANNOT_RUNNING = true;
    ANNOT_PID = String(data.pid);
    annotRenderStatus();
    showToast(data.already_running ? '既に起動しています' : 'アノテーションツールを起動しました', false);
  }} catch (e) {{
    showToast('通信エラー: ' + e, true);
  }}
}}
</script>
</body>
</html>'''


# ---------------------------------------------------------------------------
# サーバー
# ---------------------------------------------------------------------------
def handle_get(handler, path: str) -> bool:
    if path == "/annotation/status":
        handler._send_json(200, app_launcher.launch_status())
        return True
    return False


def handle_post(handler, path: str, posted: dict) -> bool:
    if path == "/annotation/launch":
        handler._send_json(200, app_launcher.launch_annotation_tool())
        return True
    return False


class Handler(JSONHandlerMixin, BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send_html(render_page())
        elif self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        elif handle_get(self, self.path):
            pass
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        try:
            posted = self._read_json_body()
            if not handle_post(self, self.path, posted):
                self.send_response(404)
                self.end_headers()
        except ValueError as e:
            self._send_json(400, dict(ok=False, message=str(e)))
        except Exception as e:  # noqa: BLE001
            self._send_json(500, dict(ok=False, message=f"予期しないエラー: {e}"))


def main():
    with ThreadingHTTPServer(("0.0.0.0", PORT), Handler) as httpd:
        print("=" * 60)
        print("アノテーションツール ランチャー を起動しました")
        print(f"  対象: {app_launcher.ANNOTATION_TOOL_MAIN}")
        print(f"  ローカル: http://localhost:{PORT}")
        print("  Ctrl+C で終了")
        print("=" * 60)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n終了しました")


if __name__ == "__main__":
    main()
