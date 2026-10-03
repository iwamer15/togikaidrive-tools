#!/usr/bin/env python3
"""
ラズパイ実機パネル
==================
ラズパイ上の設定エディタ(モーター校正ウィジェットなど、実機のPCA9685に触れる機能)を、
ターミナル操作なしで「配置 → 起動 → 開く → 停止」できるようにするローカルツール。

背景:
    Mac/Windows上で動いているポータルのモーターは「モック」で、実機には何も出力しない。
    車を実際に動かす確認は、ラズパイ上で設定エディタを動かす必要がある。しかしラズパイの
    ターミナルで毎回起動するのは慣れていないメンバーには難しいため、既に保存済みの
    SSH接続設定(shared/ssh_connection.json)を使い、ブラウザのボタンだけで済ませる。

やること:
    1. ツールを配置/更新: shared/・togikaidrive-config-editor/・raspi-editor/ を
       ラズパイの <togikaidrive-devの親>/lab/ へ送る(rsync不要。Windowsでもsshだけで動く)
    2. 実機制御(設定エディタ)を起動/停止: ラズパイ上で軽量モード(--no-ml)で起動する。
       sshを切っても動き続け、停止時はSIGTERM→設定エディタ側でモーターを0に戻してから終了する
    3. モーター停止: 起動中の設定エディタにスロットル/ステアリング0を送る

使い方:
    python3 server.py
    → ブラウザで http://localhost:8904 を開く
"""
from __future__ import annotations

import json
import posixpath
import socket
import sys
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8904
HERE = Path(__file__).resolve().parent
TOOLS_ROOT = HERE.parent  # lab/ (兄弟ツールとshared/がある場所)
REPO_ROOT = TOOLS_ROOT.parent  # ト技会-minicar/ (togikaidrive-dev/ がある場所)

# ポータル(togikaidrive-portal)がタブとして埋め込む際に使うメタ情報
PANEL_ID = "raspi"
PANEL_TITLE = "ラズパイ実機"
PANEL_ICON = "🍓"

sys.path.insert(0, str(TOOLS_ROOT))
from shared import ui_kit  # noqa: E402
from shared import remote_link  # noqa: E402
from shared.http_kit import JSONHandlerMixin  # noqa: E402

PALETTE = ui_kit.PALETTE

EDITOR_PORT = 8899                      # ラズパイ上の設定エディタのポート
DAEMON_NAME = "config-editor"           # /tmp/togikai-config-editor.pid|log
DEPLOY_DIRS = ["shared", "togikaidrive-config-editor", "raspi-editor"]
# ssh_connection.jsonは各PC固有の接続情報、templatesは各自の保存済みテンプレートなので送らない
DEPLOY_EXCLUDE = {"ssh_connection.json", "templates"}


# ---------------------------------------------------------------------------
# ラズパイ側の配置場所の決定
# ---------------------------------------------------------------------------
def _connection() -> dict:
    conn = remote_link.load_connection()
    if not conn.get("host"):
        raise ValueError("接続設定がありません。「設定エディタ → 🔌 ラズパイ連携」で接続設定を保存してください")
    if not conn.get("remote_base_dir"):
        raise ValueError("ラズパイ上のtogikaidrive-devのパスが未設定です(「ラズパイ連携」の接続設定)")
    return conn


def _layout(conn: dict) -> dict:
    """PC側と同じく、ツールはlab/の中に置き、そのlab/をラズパイ上のtogikaidrive-devの
    親ディレクトリ直下に作る(設定エディタはlab/の1つ上のtogikaidrive-dev/config.pyを編集する作りのため)。
    起動するのは実機制御用の入口であるlab/raspi-editor/。"""
    base = conn["remote_base_dir"].rstrip("/")
    lab = posixpath.join(posixpath.dirname(base), "lab")
    return dict(
        lab=lab,
        workdir=posixpath.join(lab, "raspi-editor"),
        python=posixpath.join(base, "venv", "bin", "python3"),
    )


def _editor_url(conn: dict) -> str:
    """設定エディタ(ラズパイ)のURL。`xxx.local`のようなホスト名はIPv6でも解決されることがあり、
    設定エディタはIPv4でしか待ち受けていないため、ブラウザがIPv6側に行って
    ERR_ADDRESS_UNREACHABLEになる場合がある。名前解決できればIPv4アドレスで返す。"""
    host = conn["host"]
    try:
        infos = socket.getaddrinfo(host, EDITOR_PORT, socket.AF_INET, socket.SOCK_STREAM)
        if infos:
            host = infos[0][4][0]
    except OSError:
        pass  # 解決できなければ設定のホスト名のまま返す
    return f"http://{host}:{EDITOR_PORT}"


# ---------------------------------------------------------------------------
# 操作
# ---------------------------------------------------------------------------
def get_status() -> dict:
    conn = _connection()
    st = remote_link.remote_daemon_status(conn, DAEMON_NAME, port=EDITOR_PORT)
    return dict(
        host=conn["host"], user=conn["user"], remote_base_dir=conn["remote_base_dir"],
        editor_url=_editor_url(conn), **st,
    )


def deploy() -> dict:
    conn = _connection()
    layout = _layout(conn)
    count = remote_link.push_directories_tar(
        conn, TOOLS_ROOT, DEPLOY_DIRS, layout["lab"], exclude_names=DEPLOY_EXCLUDE)
    return dict(files=count, destination=layout["lab"])


def start_editor() -> dict:
    conn = _connection()
    layout = _layout(conn)
    return remote_link.remote_daemon_start(
        conn, DAEMON_NAME, layout["workdir"], '"$PY" -u server.py --no-ml',
        python_exe=layout["python"])


def _post_motor_stop(conn: dict) -> None:
    req = urllib.request.Request(
        f"{_editor_url(conn)}/motor/stop", data=b"{}", method="POST",
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=4) as res:
        body = json.loads(res.read().decode("utf-8"))
    if not body.get("ok"):
        raise ValueError(body.get("message") or "モーター停止に失敗しました")


def motor_stop() -> dict:
    """起動中の設定エディタにスロットル/ステアリング0を送る。設定エディタに届かない
    場合は、プロセス自体をSIGTERMで止める(終了時にモーターを0へ戻す処理が走る)。"""
    conn = _connection()
    try:
        _post_motor_stop(conn)
        return dict(method="http")
    except (urllib.error.URLError, OSError, ValueError):
        result = remote_link.remote_daemon_stop(conn, DAEMON_NAME, "server.py")
        return dict(method="process_stop", result=result)


def stop_editor() -> dict:
    conn = _connection()
    try:
        _post_motor_stop(conn)  # 先にモーターを0へ(届かなくても続行)
    except (urllib.error.URLError, OSError, ValueError):
        pass
    return dict(result=remote_link.remote_daemon_stop(conn, DAEMON_NAME, "server.py"))


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
def render_page() -> str:
    return HTML_SHELL.replace("__ROOT_CSS__", ROOT_CSS).replace("__COMMON_JS__", ui_kit.COMMON_JS)


ROOT_CSS = f'''
  :root {{
    --navy: {PALETTE["navy"]}; --steel: {PALETTE["steel"]}; --steel-soft: {PALETTE["steel_soft"]};
    --cyan: {PALETTE["cyan"]}; --orange: {PALETTE["orange"]}; --card-bg: {PALETTE["card_bg"]};
    --text-dark: {PALETTE["text_dark"]}; --muted: {PALETTE["muted"]}; --orange-tint: {PALETTE["orange_tint"]};
  }}
'''

HTML_SHELL = '''<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ラズパイ実機パネル</title>
<style>
__ROOT_CSS__
  * { box-sizing: border-box; }
  body {
    margin: 0; background: #F7F8FB; color: var(--text-dark);
    font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Yu Gothic", "Segoe UI", sans-serif;
    padding-bottom: 2rem;
  }
  header { background: var(--navy); color: #fff; padding: 1.4rem 1.5rem; }
  header .eyebrow { color: var(--cyan); font-size: 0.75rem; font-weight: 700; letter-spacing: 0.12em; }
  header h1 { margin: 0.3rem 0 0.4rem; font-size: 1.4rem; }
  header p { margin: 0; color: #B9C0D4; font-size: 0.8rem; }

  main { max-width: 820px; margin: 1.2rem auto 0; padding: 0 1.2rem; display: flex; flex-direction: column; gap: 1.1rem; }
  .card { background: #fff; border-radius: 16px; box-shadow: 0 8px 24px rgba(16,19,26,0.08); padding: 1.2rem 1.4rem; }
  .card h2 { margin: 0 0 0.6rem; font-size: 1.05rem; }
  .card .sub { margin: 0 0 1rem; color: var(--muted); font-size: 0.82rem; line-height: 1.6; }

  .raspi-warn { background: var(--orange-tint); border-left: 4px solid var(--orange); border-radius: 8px;
    padding: 0.8rem 1rem; font-size: 0.82rem; line-height: 1.7; }
  .raspi-warn ul { margin: 0.3rem 0 0; padding-left: 1.2rem; }

  table.raspi-info { width: 100%; border-collapse: collapse; font-size: 0.83rem; }
  table.raspi-info td { padding: 0.3rem 0.3rem; border-top: 1px solid #EEF0F5; }
  table.raspi-info td:first-child { color: var(--muted); width: 38%; }

  button.raspi-primary { background: var(--orange); color: #fff; border: none; padding: 0.65rem 1.3rem;
    border-radius: 999px; font-size: 0.92rem; font-weight: 700; cursor: pointer; }
  button.raspi-secondary { background: var(--steel); color: #fff; border: none; padding: 0.6rem 1.1rem;
    border-radius: 999px; font-size: 0.85rem; font-weight: 700; cursor: pointer; }
  button.raspi-primary:disabled, button.raspi-secondary:disabled { opacity: 0.45; cursor: default; }
  button.raspi-danger { background: #B00020; color: #fff; border: none; padding: 0.9rem 1.6rem;
    border-radius: 12px; font-size: 1.05rem; font-weight: 800; cursor: pointer; width: 100%; }
  a.raspi-open { display: inline-block; background: var(--cyan); color: #fff; text-decoration: none;
    padding: 0.6rem 1.1rem; border-radius: 999px; font-size: 0.85rem; font-weight: 700; }
  a.raspi-open.disabled { opacity: 0.45; pointer-events: none; }
  .raspi-btn-row { display: flex; flex-wrap: wrap; gap: 0.6rem; align-items: center; }

  .raspi-badge { display: inline-block; padding: 0.3rem 0.75rem; border-radius: 999px; font-size: 0.78rem; font-weight: 700; }
  .raspi-badge.idle { background: var(--card-bg); color: var(--muted); }
  .raspi-badge.starting { background: #FFF3CD; color: #8A6D00; }
  .raspi-badge.ready { background: #0F5132; color: #C7F0DA; }
  .raspi-badge.error { background: var(--orange-tint); color: var(--orange); }

  #raspi-log-box { background: var(--navy); color: #C7CEDE; border-radius: 10px; padding: 0.8rem 1rem; margin-top: 0.8rem;
    font-family: "SF Mono", "Menlo", "Consolas", monospace; font-size: 0.74rem; line-height: 1.5;
    height: 200px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; }
  #raspi-msg { margin-top: 0.7rem; font-size: 0.82rem; color: var(--muted); min-height: 1.2em; }

  #toast { position: fixed; top: 1rem; left: 50%; transform: translateX(-50%) translateY(-140%);
    background: var(--navy); color: #fff; padding: 0.7rem 1.2rem; border-radius: 10px;
    font-size: 0.85rem; transition: transform 0.25s ease; z-index: 10; max-width: 90vw; }
  #toast.show { transform: translateX(-50%) translateY(0); }
  #toast.error { background: var(--orange); }
</style>
</head>
<body>
<header>
  <div class="eyebrow">TOGIKAIDRIVE · RASPBERRY PI</div>
  <h1>🍓 ラズパイ実機パネル</h1>
  <p>ラズパイ上の設定エディタをボタンで起動し、モーター校正など実機に触れる操作を行います。</p>
</header>
<div id="toast"></div>
<main>
  <div class="card">
    <div class="raspi-warn">
      ⚠️ <b>実際にモーターが動きます。</b>
      <ul>
        <li>最初は<b>タイヤが床から浮くように車体を持ち上げて</b>から試してください。</li>
        <li>低速(スロットル ±0.10〜0.15程度)から少しずつ上げてください。</li>
        <li>いつでも電源・ジョイスティックで物理的に止められる状態で操作してください。ネットワーク経由の停止は補助です。</li>
      </ul>
    </div>
  </div>

  <div class="card">
    <h2>🔌 接続先</h2>
    <p class="sub">接続先は「設定エディタ → 🔌 ラズパイ連携」の接続設定を使います(変更もそこで行います)。</p>
    <table class="raspi-info">
      <tr><td>ホスト</td><td id="raspi-host">-</td></tr>
      <tr><td>togikaidrive-dev</td><td id="raspi-base">-</td></tr>
    </table>
    <div class="raspi-btn-row" style="margin-top:0.9rem;">
      <button class="raspi-secondary" onclick="raspiRefresh()">状態を更新</button>
    </div>
  </div>

  <div class="card">
    <h2>① ツールを配置 / 更新</h2>
    <p class="sub">実機制御エディタ一式(shared・設定エディタ・raspi-editor)をラズパイの<code>lab/</code>へ送ります(初回と、ツールを更新した時に実行)。ラズパイ側にしか無いファイルは消しません。更新後に起動中の場合は、一度停止して起動し直してください。</p>
    <button class="raspi-primary" id="raspi-deploy-btn" onclick="raspiDeploy()">ツールを配置 / 更新</button>
  </div>

  <div class="card">
    <h2>② 実機制御エディタを起動</h2>
    <p class="sub">ラズパイ上で軽量モードで起動します。起動には数秒かかります。「開く」で別タブに開く<b>実機制御エディタ</b>の「操作」タブ → 「🔧 モーター校正」を使ってください。<b>赤いヘッダーと赤い帯(🍓 実機モード)の画面が実機に届く画面</b>です。このポータル(紺のヘッダー)の画面は、モーターがモックなので車は動きません。</p>
    <p>状態: <span id="raspi-badge" class="raspi-badge idle">未確認</span></p>
    <div class="raspi-btn-row">
      <button class="raspi-primary" id="raspi-start-btn" onclick="raspiStart()">起動</button>
      <button class="raspi-secondary" id="raspi-stop-btn" onclick="raspiStop()">停止</button>
      <a class="raspi-open disabled" id="raspi-open-link" href="#" target="_blank" rel="noopener">開く ↗</a>
    </div>
    <div id="raspi-msg"></div>
    <div id="raspi-log-box">状態を更新するとラズパイ側のログが表示されます。</div>
  </div>

  <div class="card">
    <h2>🛑 モーター停止</h2>
    <p class="sub">起動中の設定エディタに、スロットル・ステアリング0を送ります。届かない場合はプロセスごと停止します(終了時にモーターは0へ戻ります)。</p>
    <button class="raspi-danger" onclick="raspiMotorStop()">🛑 モーターを止める</button>
  </div>
</main>
<script>
__COMMON_JS__

let RASPI_POLL = null;

function raspiSetMsg(text) { document.getElementById('raspi-msg').textContent = text || ''; }

async function raspiApi(method, path) {
  const res = await fetch(path, {method});
  const data = await res.json();
  if (!data.ok) throw new Error(data.message || '失敗しました');
  return data;
}

function raspiRender(st) {
  document.getElementById('raspi-host').textContent = `${st.user}@${st.host}`;
  document.getElementById('raspi-base').textContent = st.remote_base_dir;
  const badge = document.getElementById('raspi-badge');
  const link = document.getElementById('raspi-open-link');
  if (st.running && st.listening) {
    badge.className = 'raspi-badge ready'; badge.textContent = '起動中(利用可)';
  } else if (st.running) {
    badge.className = 'raspi-badge starting'; badge.textContent = '起動中(準備中...)';
  } else {
    badge.className = 'raspi-badge idle'; badge.textContent = '停止中';
  }
  document.getElementById('raspi-start-btn').disabled = st.running;
  document.getElementById('raspi-stop-btn').disabled = !st.running;
  if (st.running && st.listening) {
    link.classList.remove('disabled'); link.href = st.editor_url;
  } else {
    link.classList.add('disabled'); link.href = '#';
  }
  const box = document.getElementById('raspi-log-box');
  box.textContent = st.log && st.log.trim() ? st.log : '(ログはまだありません)';
  box.scrollTop = box.scrollHeight;
}

async function raspiRefresh() {
  try {
    raspiSetMsg('ラズパイに問い合わせ中...');
    const data = await raspiApi('GET', '/raspi/status');
    raspiRender(data);
    raspiSetMsg('');
    return data;
  } catch (e) {
    const badge = document.getElementById('raspi-badge');
    badge.className = 'raspi-badge error'; badge.textContent = '取得失敗';
    raspiSetMsg(e.message);
    showToast(e.message, true);
    return null;
  }
}

function raspiStopPolling() { if (RASPI_POLL) { clearInterval(RASPI_POLL); RASPI_POLL = null; } }

function raspiPollUntilReady() {
  raspiStopPolling();
  let tries = 0;
  RASPI_POLL = setInterval(async () => {
    tries += 1;
    const st = await raspiRefresh();
    if ((st && st.running && st.listening) || tries >= 30) raspiStopPolling();
  }, 2500);
}

async function raspiDeploy() {
  const btn = document.getElementById('raspi-deploy-btn');
  btn.disabled = true; raspiSetMsg('ラズパイへ送信中...');
  try {
    const data = await raspiApi('POST', '/raspi/deploy');
    showToast(`${data.files}個のファイルを配置しました`, false);
    raspiSetMsg(`配置完了: ${data.destination} (${data.files}ファイル)`);
  } catch (e) { showToast(e.message, true); raspiSetMsg(e.message); }
  btn.disabled = false;
}

async function raspiStart() {
  document.getElementById('raspi-start-btn').disabled = true;
  raspiSetMsg('起動しています...');
  try {
    const data = await raspiApi('POST', '/raspi/editor/start');
    showToast(data.already ? '既に起動しています' : '起動しました(準備ができるまで数秒かかります)', false);
    raspiPollUntilReady();
  } catch (e) { showToast(e.message, true); raspiSetMsg(e.message); await raspiRefresh(); }
}

async function raspiStop() {
  if (!confirm('ラズパイ上の設定エディタを停止します。モーターは0に戻ります。よろしいですか?')) return;
  raspiStopPolling(); raspiSetMsg('停止しています...');
  try {
    const data = await raspiApi('POST', '/raspi/editor/stop');
    showToast(`停止しました(${data.result})`, false);
  } catch (e) { showToast(e.message, true); }
  await raspiRefresh();
}

async function raspiMotorStop() {
  try {
    const data = await raspiApi('POST', '/raspi/motor/stop');
    showToast(data.method === 'http' ? 'モーターに停止(0)を送りました' : '設定エディタごと停止しました', false);
  } catch (e) { showToast('停止に失敗: ' + e.message + ' / 電源・ジョイスティックで物理的に止めてください', true); }
}
</script>
</body>
</html>'''


# ---------------------------------------------------------------------------
# サーバー
# ---------------------------------------------------------------------------
def _ok(handler, **payload) -> None:
    handler._send_json(200, dict(ok=True, **payload))


def handle_get(handler, path: str) -> bool:
    # ポータルのdo_GETは例外を捕まえないため、SSH失敗などはここでJSONエラーにする
    if path == "/raspi/status":
        try:
            _ok(handler, **get_status())
        except ValueError as e:
            handler._send_json(400, dict(ok=False, message=str(e)))
        return True
    return False


def handle_post(handler, path: str, posted: dict) -> bool:
    if path == "/raspi/deploy":
        _ok(handler, **deploy())
        return True
    if path == "/raspi/editor/start":
        _ok(handler, **start_editor())
        return True
    if path == "/raspi/editor/stop":
        _ok(handler, **stop_editor())
        return True
    if path == "/raspi/motor/stop":
        _ok(handler, **motor_stop())
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
        print("ラズパイ実機パネル を起動しました")
        print(f"  ローカル: http://localhost:{PORT}")
        print("  Ctrl+C で終了")
        print("=" * 60)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n終了しました")


if __name__ == "__main__":
    main()
