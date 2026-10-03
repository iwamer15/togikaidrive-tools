#!/usr/bin/env python3
"""
学習実行パネル
==============
`togikaidrive-dev/train_pytorch.py`(対話式の機械学習実行スクリプト)を、
ブラウザから起動・進捗監視できるようにするローカルツール。

train_pytorch.py には CLI引数や環境変数での非対話実行オプションが無く、
`main()`実行時に複数の`input()`プロンプトが順に現れる設計になっている。
このツールは train_pytorch.py 自体を一切変更せず、サブプロセスとして起動して
標準入力に決まった順で回答を流し込み(実際に人が打つのと同じ操作を自動化する
だけ)、標準出力をポーリングでブラウザにリアルタイム表示する。

v1のスコープ: 測距データ(nn)のみ
    実際に収集済みのデータはすべて測距センサーのみ(画像なし)のため、
    学習プランは "nn" に固定している。画像ベース(donkeycar/resnet18等)は、
    学習完了後のモデル変換確認プロンプト(Jetson/RPi実行時のみ)など条件分岐が
    増えて標準入力の自動応答が複雑になるため、カメラ画像データの収集が
    実際に始まってから対応する(削除ではなく将来の拡張候補)。

使い方:
    python3 server.py
    → ブラウザで http://localhost:8901 を開く
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8901
HERE = Path(__file__).resolve().parent
TOOLS_ROOT = HERE.parent  # lab/ (兄弟ツールとshared/がある場所)
REPO_ROOT = TOOLS_ROOT.parent  # ト技会-minicar/ (togikaidrive-dev/ がある場所)
TOGIKAIDRIVE_DEV_DIR = REPO_ROOT / "togikaidrive-dev"
CONFIG_EDITOR_DIR = TOOLS_ROOT / "togikaidrive-config-editor"
DATA_PREPROCESS_DIR = TOOLS_ROOT / "data-preprocessing-tool"

# ポータル(togikaidrive-portal)がタブとして埋め込む際に使うメタ情報
PANEL_ID = "train"
PANEL_TITLE = "学習実行"
PANEL_ICON = "🚀"


def _load_sibling_module(name: str, path: Path):
    """兄弟ツールのserver.pyを読み込む。両方とも同名(server.py)なので、
    素朴に `import server` を2回行うと sys.modules["server"] のキャッシュ衝突で
    2つ目が1つ目のモジュールを指してしまう。それぞれ別名でロードして回避する。"""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# デザイン(PALETTE)・HTMLエスケープは3ツール共通のshared/ui_kit.pyを使う。
# config.py読み取り・データフォルダ一覧は、既存の2ツールをそのまま再利用する。
# config_editorを先に普通にimportしておくことで、data_tool内部の
# `sys.path.insert(...); import server as config_editor` が同じモジュールを
# 再利用できるようにする(sys.modules["server"]を先に埋めておく)。
sys.path.insert(0, str(TOOLS_ROOT))
from shared import ui_kit  # noqa: E402
from shared.http_kit import JSONHandlerMixin  # noqa: E402

sys.path.insert(0, str(CONFIG_EDITOR_DIR))
import server as config_editor  # noqa: E402

data_tool = _load_sibling_module("togikaidrive_data_preprocessing_server", DATA_PREPROCESS_DIR / "server.py")

PALETTE = ui_kit.PALETTE
_html_escape = ui_kit.html_escape

TRAINING_KEYS = ["EPOCHS", "BATCH_SIZE", "HIDDEN_DIM", "NUM_HIDDEN_LAYERS", "MODEL_DIR"]


# ---------------------------------------------------------------------------
# 学習プロセスの管理
# ---------------------------------------------------------------------------
TRAINING_STATE: dict = {
    "status": "idle",  # idle | running | stopping | completed | failed | stopped
    "log": [],
    "proc": None,
    "folder": None,
    "epochs": None,
    "started_at": None,
    "finished_at": None,
    "error": None,
}
STATE_LOCK = threading.Lock()


def current_training_config() -> dict:
    text = config_editor.CONFIG_PATH.read_text(encoding="utf-8")
    return config_editor.read_key_values(TRAINING_KEYS, text)


def _read_output(proc: subprocess.Popen) -> None:
    try:
        for line in proc.stdout:
            with STATE_LOCK:
                if TRAINING_STATE["proc"] is not proc:
                    break  # 別の実行に切り替わっていたら追記しない
                TRAINING_STATE["log"].append(line.rstrip("\n"))
    finally:
        returncode = proc.wait()
        with STATE_LOCK:
            if TRAINING_STATE["proc"] is proc:
                if TRAINING_STATE["status"] == "stopping":
                    TRAINING_STATE["status"] = "stopped"
                else:
                    TRAINING_STATE["status"] = "completed" if returncode == 0 else "failed"
                TRAINING_STATE["finished_at"] = time.time()


def start_training(folder: str, epochs, continue_training: bool) -> None:
    with STATE_LOCK:
        if TRAINING_STATE["status"] == "running":
            raise ValueError("既に学習が実行中です。完了または停止してから開始してください")

    folders = data_tool.list_data_folders()
    folder_names = [f["name"] for f in folders]
    if not folder_names:
        raise ValueError("データフォルダが見つかりません(前処理ツールで確認してください)")
    if folder not in folder_names:
        raise ValueError(f"データフォルダが見つかりません: {folder}")

    # train_pytorch.py の get_data_directory() は data_folders.sort() で
    # 「昇順(古い順)」に並べ替えてから番号を振る。このツールの一覧(list_data_folders)は
    # 閲覧しやすいよう新しい順にしているため、番号の対応関係をここで正しく変換する。
    ascending = sorted(folder_names)
    folder_number = ascending.index(folder) + 1

    venv_python = TOGIKAIDRIVE_DEV_DIR / "venv" / "bin" / "python3"
    python_exe = str(venv_python) if venv_python.exists() else sys.executable

    answers = []
    if len(folder_names) > 1:
        answers.append(str(folder_number))  # プロンプト1: データフォルダ選択
    answers.append("1")  # プロンプト2: 学習モデル選択(nn固定)
    answers.append(str(int(epochs)) if epochs else "")  # プロンプト3: エポック数
    answers.append("Y")  # プロンプト4: この設定で学習を開始しますか
    # プロンプト5: 継続学習の確認(既存モデルが無ければ発生しないが、
    # 発生しても後続のプロンプトが無いため多めに送っておいても安全)
    answers.append("y" if continue_training else "n")
    stdin_text = "\n".join(answers) + "\n"

    try:
        proc = subprocess.Popen(
            [python_exe, "train_pytorch.py"],
            cwd=str(TOGIKAIDRIVE_DEV_DIR),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
    except Exception as e:
        raise ValueError(f"学習プロセスの起動に失敗しました: {e}")

    with STATE_LOCK:
        TRAINING_STATE.update(
            status="running", log=[], proc=proc, folder=folder, epochs=epochs,
            started_at=time.time(), finished_at=None, error=None,
        )

    try:
        proc.stdin.write(stdin_text)
        proc.stdin.close()
    except Exception:
        pass  # プロセス側が既に終了している等、書き込み失敗は _read_output 側のログで分かる

    threading.Thread(target=_read_output, args=(proc,), daemon=True).start()


def stop_training() -> None:
    with STATE_LOCK:
        proc = TRAINING_STATE["proc"]
        if not proc or TRAINING_STATE["status"] != "running":
            raise ValueError("実行中の学習がありません")
        TRAINING_STATE["status"] = "stopping"
    try:
        proc.terminate()
    except Exception:
        pass


def get_status() -> dict:
    with STATE_LOCK:
        return dict(
            status=TRAINING_STATE["status"], folder=TRAINING_STATE["folder"],
            epochs=TRAINING_STATE["epochs"], started_at=TRAINING_STATE["started_at"],
            finished_at=TRAINING_STATE["finished_at"], log_length=len(TRAINING_STATE["log"]),
        )


def get_log(since: int) -> dict:
    with STATE_LOCK:
        lines = TRAINING_STATE["log"][since:]
        total = len(TRAINING_STATE["log"])
        status = TRAINING_STATE["status"]
    return dict(lines=lines, total=total, status=status)


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
def render_page() -> str:
    cfg = current_training_config()
    folders = data_tool.list_data_folders()
    folders_json = json.dumps(folders, ensure_ascii=False)
    cfg_json = json.dumps(cfg, ensure_ascii=False)
    return (
        HTML_SHELL
        .replace("__FOLDERS__", folders_json)
        .replace("__CONFIG__", cfg_json)
        .replace("__CONFIG_PATH__", _html_escape(str(config_editor.CONFIG_PATH)))
    )


HTML_SHELL = f'''<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>学習実行パネル</title>
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

  main {{ max-width: 900px; margin: 1.2rem auto 0; padding: 0 1.2rem; display: flex; flex-direction: column; gap: 1.1rem; }}
  .card {{ background: #fff; border-radius: 16px; box-shadow: 0 8px 24px rgba(16,19,26,0.08); padding: 1.2rem 1.4rem; }}
  .card h2 {{ margin: 0 0 0.6rem; font-size: 1.05rem; }}
  .card .sub {{ margin: 0 0 1rem; color: var(--muted); font-size: 0.82rem; }}

  table.cfg {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
  table.cfg td {{ padding: 0.35rem 0.4rem; border-top: 1px solid #EEF0F5; }}
  table.cfg td:first-child {{ color: var(--muted); }}
  table.cfg td:last-child {{ font-weight: 700; text-align: right; }}

  .field {{ margin-bottom: 0.9rem; }}
  .field label {{ display: block; font-weight: 700; font-size: 0.85rem; margin-bottom: 0.3rem; }}
  .field select, .field input[type=number] {{
    width: 100%; padding: 0.55rem 0.7rem; border: 1px solid #D8DCE6; border-radius: 8px; font-size: 0.95rem;
  }}
  .chk-row {{ display: flex; align-items: center; gap: 0.5rem; font-size: 0.85rem; margin-bottom: 1rem; }}

  button.primary {{
    background: var(--orange); color: #fff; border: none; padding: 0.7rem 1.4rem; border-radius: 999px;
    font-size: 0.95rem; font-weight: 700; cursor: pointer;
  }}
  button.primary:disabled {{ opacity: 0.5; cursor: default; }}
  button.secondary {{
    background: var(--steel); color: #fff; border: none; padding: 0.6rem 1.1rem; border-radius: 999px;
    font-size: 0.85rem; font-weight: 700; cursor: pointer;
  }}
  button.secondary:disabled {{ opacity: 0.5; cursor: default; }}

  .status-badge {{
    display: inline-block; padding: 0.3rem 0.7rem; border-radius: 999px; font-size: 0.78rem; font-weight: 700;
  }}
  .status-idle {{ background: var(--card-bg); color: var(--muted); }}
  .status-running {{ background: #FFF3CD; color: #8A6D00; }}
  .status-completed {{ background: #0F5132; color: #C7F0DA; }}
  .status-failed {{ background: var(--orange-tint); color: var(--orange); }}
  .status-stopped, .status-stopping {{ background: var(--card-bg); color: var(--muted); }}

  #log-box {{
    background: var(--navy); color: #C7CEDE; border-radius: 10px; padding: 0.9rem 1rem;
    font-family: "SF Mono", "Menlo", "Consolas", monospace; font-size: 0.76rem; line-height: 1.5;
    height: 380px; overflow-y: auto; white-space: pre-wrap; word-break: break-all;
  }}
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
  <div class="eyebrow">TOGIKAIDRIVE · TRAINING</div>
  <h1>学習実行パネル</h1>
  <p>train_pytorch.py をブラウザから起動し、進捗をリアルタイムに確認します。</p>
</header>
<div id="toast"></div>
<main>
  <div class="card">
    <h2>⚙️ 現在のconfig.py設定(参考・読み取り専用)</h2>
    <p class="sub">値を変更したい場合はtogikaidrive-config-editorで変更してください。対象: __CONFIG_PATH__</p>
    <table class="cfg" id="cfg-table"></table>
  </div>

  <div class="card">
    <h2>▶️ 学習の実行</h2>
    <p class="sub">v1は測距データ(nnプラン)専用です。画像データを使うプラン(donkeycar/resnet18等)は今後の拡張候補です。</p>
    <div class="field">
      <label>データフォルダ</label>
      <select id="folder-select"></select>
    </div>
    <div class="field">
      <label>エポック数(空欄でconfig.pyのデフォルトを使用)</label>
      <input type="number" id="epochs-input" min="1" placeholder="config.pyのEPOCHSを使用">
    </div>
    <div class="chk-row">
      <input type="checkbox" id="continue-checkbox">
      <label for="continue-checkbox" style="font-weight:400;">既存の同種モデルがあれば継続学習する(未チェック=毎回新規学習)</label>
    </div>
    <button class="primary" id="start-btn" onclick="startTraining()">学習を開始</button>
    <button class="secondary" id="stop-btn" onclick="stopTraining()" disabled style="margin-left:0.6rem;">停止</button>
  </div>

  <div class="card">
    <h2>📋 実行状況</h2>
    <p>状態: <span id="status-badge" class="status-badge status-idle">待機中</span></p>
    <div id="log-box">まだ学習を開始していません。</div>
  </div>
</main>
<script>
const TRAIN_FOLDERS = __FOLDERS__;
const CONFIG = __CONFIG__;
let POLL_TIMER = null;
let LOG_SINCE = 0;

function showToast(msg, isError) {{
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = isError ? 'show error' : 'show';
  setTimeout(() => {{ t.className = ''; }}, 3200);
}}

function renderConfigTable() {{
  const labels = {{EPOCHS: 'エポック数', BATCH_SIZE: 'バッチサイズ', HIDDEN_DIM: '隠れ層ノード数',
                   NUM_HIDDEN_LAYERS: '隠れ層数', MODEL_DIR: 'モデル保存先'}};
  const rows = Object.keys(labels).map(k => `<tr><td>${{labels[k]}}</td><td>${{CONFIG[k] ?? '-'}}</td></tr>`).join('');
  document.getElementById('cfg-table').innerHTML = rows;
  const epochsInput = document.getElementById('epochs-input');
  if (CONFIG.EPOCHS) epochsInput.placeholder = `config.pyのデフォルト: ${{CONFIG.EPOCHS}}`;
}}
renderConfigTable();

function renderFolderSelect() {{
  const sel = document.getElementById('folder-select');
  if (!TRAIN_FOLDERS.length) {{
    sel.innerHTML = '<option value="">(データフォルダがありません)</option>';
    return;
  }}
  sel.innerHTML = TRAIN_FOLDERS.map(f => `<option value="${{f.name}}">${{f.name}} (${{f.total_records}}件)</option>`).join('');
}}
renderFolderSelect();

async function startTraining() {{
  const folder = document.getElementById('folder-select').value;
  if (!folder) {{ showToast('データフォルダを選択してください', true); return; }}
  const epochs = document.getElementById('epochs-input').value;
  const continueTraining = document.getElementById('continue-checkbox').checked;
  try {{
    const res = await fetch('/train/start', {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{folder, epochs: epochs || null, continue_training: continueTraining}}),
    }});
    const data = await res.json();
    if (!data.ok) {{ showToast(data.message || '開始に失敗しました', true); return; }}
    LOG_SINCE = 0;
    document.getElementById('log-box').textContent = '';
    showToast('学習を開始しました', false);
    startPolling();
  }} catch (e) {{
    showToast('通信エラー: ' + e, true);
  }}
}}

async function stopTraining() {{
  if (!confirm('実行中の学習を停止しますか？')) return;
  try {{
    const res = await fetch('/train/stop', {{method: 'POST'}});
    const data = await res.json();
    if (!data.ok) showToast(data.message || '停止に失敗しました', true);
  }} catch (e) {{
    showToast('通信エラー: ' + e, true);
  }}
}}

const STATUS_LABELS = {{
  idle: '待機中', running: '実行中', stopping: '停止処理中', completed: '完了',
  failed: '失敗', stopped: '停止しました',
}};

function updateStatusUI(status) {{
  const badge = document.getElementById('status-badge');
  badge.className = 'status-badge status-' + status;
  badge.textContent = STATUS_LABELS[status] || status;
  const running = (status === 'running' || status === 'stopping');
  document.getElementById('start-btn').disabled = running;
  document.getElementById('stop-btn').disabled = !running;
}}

async function pollLog() {{
  try {{
    const res = await fetch('/train/log?since=' + LOG_SINCE);
    const data = await res.json();
    if (data.lines && data.lines.length) {{
      const box = document.getElementById('log-box');
      const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 20;
      box.textContent += (LOG_SINCE > 0 ? '\\n' : '') + data.lines.join('\\n');
      LOG_SINCE = data.total;
      if (atBottom) box.scrollTop = box.scrollHeight;
    }}
    updateStatusUI(data.status);
    if (data.status !== 'running' && data.status !== 'stopping') {{
      stopPolling();
    }}
  }} catch (e) {{
    // 通信エラーはポーリングを続けたまま次回リトライ
  }}
}}

function startPolling() {{
  updateStatusUI('running');
  if (POLL_TIMER) clearInterval(POLL_TIMER);
  POLL_TIMER = setInterval(pollLog, 1500);
  pollLog();
}}

function stopPolling() {{
  if (POLL_TIMER) {{ clearInterval(POLL_TIMER); POLL_TIMER = null; }}
}}

// ページを開いた時点で既に実行中の学習があれば追従表示する
(async function initStatus() {{
  try {{
    const res = await fetch('/train/log?since=0');
    const data = await res.json();
    if (data.lines && data.lines.length) {{
      document.getElementById('log-box').textContent = data.lines.join('\\n');
      LOG_SINCE = data.total;
    }}
    updateStatusUI(data.status);
    if (data.status === 'running' || data.status === 'stopping') startPolling();
  }} catch (e) {{ /* ignore */ }}
}})();
</script>
</body>
</html>'''


# ---------------------------------------------------------------------------
# サーバー
# handle_get/handle_postはこのツール単体のサーバーからも、togikaidrive-portalから
# 埋め込まれた場合からも同じ形で呼べる(戻り値Trueならこのツールが処理済み、
# Falseなら該当パスなし)。標準の`/`(ページ全体)はスタンドアロン起動時のみ
# do_GETが直接返す(ポータル側は`/`を自分のトップページとして使うため)。
# ---------------------------------------------------------------------------
def handle_get(handler, path: str) -> bool:
    if path.startswith("/train/log"):
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(path).query)
        since = int((qs.get("since") or ["0"])[0])
        handler._send_json(200, get_log(since))
        return True
    if path == "/train/status":
        handler._send_json(200, get_status())
        return True
    return False


def handle_post(handler, path: str, posted: dict) -> bool:
    if path == "/train/start":
        start_training(posted.get("folder", ""), posted.get("epochs"),
                        bool(posted.get("continue_training")))
        handler._send_json(200, dict(ok=True))
        return True
    if path == "/train/stop":
        stop_training()
        handler._send_json(200, dict(ok=True))
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
    if not TOGIKAIDRIVE_DEV_DIR.exists():
        raise SystemExit(f"togikaidrive-dev が見つかりません: {TOGIKAIDRIVE_DEV_DIR}")

    with ThreadingHTTPServer(("0.0.0.0", PORT), Handler) as httpd:
        print("=" * 60)
        print("学習実行パネル を起動しました")
        print(f"  対象: {TOGIKAIDRIVE_DEV_DIR}")
        print(f"  ローカル: http://localhost:{PORT}")
        print("  Ctrl+C で終了")
        print("=" * 60)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n終了しました")
        finally:
            with STATE_LOCK:
                proc = TRAINING_STATE["proc"]
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass


if __name__ == "__main__":
    main()
