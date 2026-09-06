#!/usr/bin/env python3
"""
モーター校正パネル
==================
togikaidrive-dev/motor.py の adjust_steering()/adjust_throttle()(ターミナルの
対話式ウィザード)と同じ校正作業を、ブラウザから実行できるようにするローカル
ツール。決定した値はそのまま config.py に保存する(config editorと同じ安全な
書き込み処理をそのまま再利用する)。

- 標準ライブラリのみで動作(pip install不要)
- Adafruit_PCA9685 が無い環境(このリポジトリの開発機など)では自動的に
  モック(ログ出力のみ)にフォールバックし、UIと保存フローだけを安全に確認できる
- motor.py 自体は一切変更しない。Motor クラスの公開インターフェース
  (set_steering_pwm_value / set_throttle_pwm_value / self.pwm.set_pwm /
  self.CHANNEL_STEERING / self.CHANNEL_THROTTLE)を外から使うだけ

使い方:
    python3 server.py
    → ブラウザで http://localhost:8900 を開く
"""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8900
HERE = Path(__file__).resolve().parent
TOOLS_ROOT = HERE.parent  # ト技会-minicar/ (togikaidrive-tools リポジトリ直下)
TOGIKAIDRIVE_DEV_DIR = TOOLS_ROOT / "togikaidrive-dev"
CONFIG_EDITOR_DIR = TOOLS_ROOT / "togikaidrive-config-editor"

# config.py の安全な読み書き(バックアップ・行単位の置換)は config editor の
# 実装をそのまま再利用する。将来 config editor に統合する際も差分が出ない。
sys.path.insert(0, str(CONFIG_EDITOR_DIR))
import server as config_editor  # noqa: E402

PALETTE = config_editor.PALETTE

VALID_RANGES = {
    "STEERING_CENTER_PWM": (100, 600),
    "STEERING_WIDTH_PWM": (0, 300),
    "THROTTLE_STOPPED_PWM": (100, 600),
    "THROTTLE_FORWARD_PWM": (100, 600),
    "THROTTLE_REVERSE_PWM": (100, 600),
}
RAW_PWM_RANGE = (100, 600)

FIELD_LABELS = {
    "STEERING_CENTER_PWM": "ステアリング中央",
    "STEERING_WIDTH_PWM": "ステアリング振れ幅",
    "THROTTLE_STOPPED_PWM": "スロットル停止(ニュートラル)",
    "THROTTLE_FORWARD_PWM": "スロットル前進最大",
    "THROTTLE_REVERSE_PWM": "スロットル後退最大",
}


# ---------------------------------------------------------------------------
# モーター初期化(実機があればMotor、無ければモック)
# ---------------------------------------------------------------------------
class MockPWM:
    def set_pwm(self, channel, on, value):
        print(f"[モック] set_pwm(channel={channel}, on={on}, value={value})")


class MockMotor:
    def __init__(self):
        self.CHANNEL_STEERING = 0
        self.CHANNEL_THROTTLE = 1
        self.pwm = MockPWM()

    def set_steering_pwm_value(self, v):
        print(f"[モック] set_steering_pwm_value({v})")

    def set_throttle_pwm_value(self, v):
        print(f"[モック] set_throttle_pwm_value({v})")

    def limit_steering_pwm(self, v):
        return v

    def cleanup(self):
        print("[モック] cleanup()")


HARDWARE_AVAILABLE = False
IMPORT_ERROR = ""
motor_instance = None


def init_motor() -> None:
    global HARDWARE_AVAILABLE, IMPORT_ERROR, motor_instance
    try:
        sys.path.insert(0, str(TOGIKAIDRIVE_DEV_DIR))
        import motor as motor_module  # noqa: E402  (togikaidrive-dev/motor.py)
        motor_instance = motor_module.Motor()
        HARDWARE_AVAILABLE = True
        print("実機のMotorを初期化しました(PCA9685接続済み)")
    except Exception as e:  # noqa: BLE001  -- 開発機やライブラリ未導入時は握りつぶしてモックへ
        IMPORT_ERROR = f"{type(e).__name__}: {e}"
        motor_instance = MockMotor()
        HARDWARE_AVAILABLE = False
        print(f"実機のMotorを初期化できなかったため、モックモードで起動します({IMPORT_ERROR})")


# ---------------------------------------------------------------------------
# config.py の読み書き(config editorの関数を再利用)
# ---------------------------------------------------------------------------
def get_current_values() -> dict:
    text = config_editor.CONFIG_PATH.read_text(encoding="utf-8")
    return config_editor.read_key_values(list(VALID_RANGES.keys()), text)


def extract_code_block(text: str, key: str) -> dict | None:
    """key が定義されている行を中心に、空行で区切られた「ひとかたまり」を
    そのまま切り出す(config editorのコードタブと同じ発想。コメント文言に
    依存せず、config.py自身の段落構造から自動で範囲を決める)。"""
    m = config_editor._line_pattern(key).search(text)
    if not m:
        return None
    lines = text.split("\n")
    line_no = text.count("\n", 0, m.start())  # 0-indexed
    start = line_no
    while start > 0 and lines[start - 1].strip() != "":
        start -= 1
    end = line_no
    while end + 1 < len(lines) and lines[end + 1].strip() != "":
        end += 1
    return dict(start_line=start + 1, code="\n".join(lines[start:end + 1]))


def render_code_block(text: str, key: str) -> str:
    block = extract_code_block(text, key)
    if block is None:
        return ""
    numbered = "\n".join(
        f"{block['start_line'] + i:>5} | {line}"
        for i, line in enumerate(block["code"].split("\n"))
    )
    return (
        f'<div class="codelog-title"><span>config.pyの現在のコード</span>'
        f'<span class="codelog-loc">config.py {block["start_line"]}行目〜</span></div>'
        f'<pre class="codelog-pre">{config_editor._html_escape(numbered)}</pre>'
    )


def write_motor_values(values: dict) -> Path:
    text = config_editor.CONFIG_PATH.read_text(encoding="utf-8")
    backup_path = config_editor._make_backup()

    for key, value in values.items():
        pat = config_editor._line_pattern(key)
        literal = str(int(value))

        def repl(m, literal=literal):
            comment = m.group(3) or ""
            new_line = f"{m.group(1)}{literal}{comment}"
            return new_line if new_line != m.group(0) else m.group(0)

        text, n = pat.subn(repl, text, count=1)
        if n == 0:
            raise ValueError(f"config.py 内に {key} の行が見つかりませんでした")

    config_editor.CONFIG_PATH.write_text(text, encoding="utf-8")
    config_editor.invalidate_cache()  # config editorを後で開いたときに最新値が反映されるように
    return backup_path


def validate_save_values(posted: dict) -> dict:
    values = {}
    for key, value in posted.items():
        if key not in VALID_RANGES:
            continue
        lo, hi = VALID_RANGES[key]
        try:
            v = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} は整数で入力してください")
        if not (lo <= v <= hi):
            raise ValueError(f"{key} は {lo}〜{hi} の範囲にしてください")
        values[key] = v
    if not values:
        raise ValueError("保存する値がありません")
    return values


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
def render_page() -> str:
    text = config_editor.CONFIG_PATH.read_text(encoding="utf-8")
    current = config_editor.read_key_values(list(VALID_RANGES.keys()), text)
    status_html = (
        f'<span class="hw-badge hw-on">🟢 実機接続中</span>'
        if HARDWARE_AVAILABLE else
        f'<span class="hw-badge hw-off" title="{config_editor._html_escape(IMPORT_ERROR)}">⚪ モック(シミュレーション)モード</span>'
    )
    return (
        HTML_SHELL
        .replace("__STATUS__", status_html)
        .replace("__CONFIG_PATH__", str(config_editor.CONFIG_PATH))
        .replace("__CURRENT_VALUES__", json.dumps(current, ensure_ascii=False))
        .replace("__FIELD_LABELS__", json.dumps(FIELD_LABELS, ensure_ascii=False))
        .replace("__STEERING_CODE__", render_code_block(text, "STEERING_CENTER_PWM"))
        .replace("__THROTTLE_CODE__", render_code_block(text, "THROTTLE_STOPPED_PWM"))
    )


HTML_SHELL = f'''<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>モーター校正パネル</title>
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
    padding-bottom: 6rem;
  }}
  header {{ background: var(--navy); color: #fff; padding: 1.4rem 1.5rem; }}
  header .eyebrow {{ color: var(--cyan); font-size: 0.75rem; font-weight: 700; letter-spacing: 0.12em; }}
  header h1 {{ margin: 0.3rem 0 0.5rem; font-size: 1.4rem; }}
  .hw-badge {{ display: inline-block; padding: 0.3rem 0.7rem; border-radius: 999px; font-size: 0.78rem; font-weight: 700; }}
  .hw-on {{ background: #0F5132; color: #C7F0DA; }}
  .hw-off {{ background: rgba(255,255,255,0.12); color: #C7CEDE; cursor: help; }}

  main {{ max-width: 720px; margin: 1.2rem auto 0; padding: 0 1.2rem; display: flex; flex-direction: column; gap: 1.1rem; }}

  .warning {{
    background: var(--orange-tint); border-radius: 12px; padding: 0.9rem 1.1rem; font-size: 0.85rem;
    color: var(--text-dark); line-height: 1.5;
  }}
  .warning b {{ color: var(--orange); }}

  .card {{ background: #fff; border-radius: 16px; box-shadow: 0 8px 24px rgba(16,19,26,0.08); padding: 1.2rem 1.4rem; }}
  .card h2 {{ margin: 0 0 0.3rem; font-size: 1.05rem; }}
  .card .card-sub {{ margin: 0 0 1rem; color: var(--muted); font-size: 0.82rem; }}

  .slider-row {{ margin-bottom: 1rem; }}
  .slider-row label {{ display: flex; justify-content: space-between; font-weight: 700; font-size: 0.88rem; margin-bottom: 0.3rem; }}
  .slider-row input[type=range] {{ width: 100%; accent-color: var(--cyan); }}

  .raw-row {{ display: flex; gap: 0.5rem; align-items: center; margin-bottom: 0.8rem; }}
  .raw-row input[type=number] {{
    flex: 1; padding: 0.5rem 0.7rem; border: 1px solid #D8DCE6; border-radius: 8px; font-size: 0.95rem;
  }}
  .raw-row button {{
    background: var(--steel); color: #fff; border: none; padding: 0.55rem 0.9rem; border-radius: 8px;
    font-size: 0.82rem; font-weight: 700; cursor: pointer; white-space: nowrap;
  }}
  .lock-buttons {{ display: flex; gap: 0.5rem; flex-wrap: wrap; margin-bottom: 0.9rem; }}
  .lock-buttons button {{
    flex: 1; background: var(--card-bg); border: 1px solid #D8DCE6; color: var(--text-dark);
    padding: 0.55rem 0.7rem; border-radius: 8px; font-size: 0.8rem; font-weight: 700; cursor: pointer;
  }}
  .lock-buttons button:hover {{ background: #E9ECF3; }}

  .codelog-title {{
    display: flex; justify-content: space-between; align-items: baseline;
    font-weight: 700; font-size: 0.78rem; color: var(--text-dark); margin: 0.9rem 0 0.35rem;
  }}
  .codelog-loc {{ font-weight: 400; font-size: 0.68rem; color: var(--muted); }}
  .codelog-pre {{
    background: var(--navy); color: #C7CEDE; border-radius: 8px; padding: 0.8rem 0.9rem;
    font-family: "SF Mono", "Menlo", "Consolas", monospace; font-size: 0.72rem; line-height: 1.55;
    overflow-x: auto; white-space: pre; margin: 0 0 1rem;
  }}

  table.summary {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
  table.summary th {{ text-align: left; color: var(--muted); font-weight: 700; font-size: 0.75rem; padding: 0.3rem 0.4rem; }}
  table.summary td {{ padding: 0.45rem 0.4rem; border-top: 1px solid #EEF0F5; }}
  .new-value {{ color: var(--orange); font-weight: 700; }}
  .new-value.unset {{ color: var(--muted); font-weight: 400; }}

  .stopbar {{
    position: fixed; left: 0; right: 0; bottom: 0; background: #fff; border-top: 1px solid #E4E7F0;
    padding: 0.9rem 1.2rem; display: flex; align-items: center; justify-content: center; gap: 1rem;
    box-shadow: 0 -6px 18px rgba(16,19,26,0.06);
  }}
  .stopbar .path {{ font-size: 0.68rem; color: var(--muted); flex: 1; text-align: right; overflow: hidden;
    text-overflow: ellipsis; white-space: nowrap; }}
  button#stop {{
    background: var(--orange); color: #fff; border: none; padding: 0.7rem 1.4rem; border-radius: 999px;
    font-size: 0.95rem; font-weight: 700; cursor: pointer;
  }}
  button#save {{
    background: var(--navy); color: #fff; border: none; padding: 0.7rem 1.4rem; border-radius: 999px;
    font-size: 0.95rem; font-weight: 700; cursor: pointer;
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
  <div class="eyebrow">TOGIKAIDRIVE · MOTOR CALIBRATION</div>
  <h1>モーター校正パネル</h1>
  __STATUS__
</header>
<div id="toast"></div>
<main>
  <div class="warning">
    ⚠️ <b>ここでの操作は実際にサーボ/ESCを動かします。</b>
    ジジっとノイズが鳴り続ける場合は壊れる兆候なので、すぐに値を戻してください。
    ページを開いただけでは何も送信されません(スライダーやボタンを操作した時だけ送信します)。
  </div>

  <section class="card">
    <h2>ライブテスト</h2>
    <p class="card-sub">現在config.pyに入っている値で、実際にどう動くかを試せます。</p>
    <div class="slider-row">
      <label>ステアリング <span id="steering-val">0.00</span></label>
      <input type="range" id="steering-slider" min="-1" max="1" step="0.05" value="0" oninput="sendLive()">
    </div>
    <div class="slider-row">
      <label>スロットル <span id="throttle-val">0.00</span></label>
      <input type="range" id="throttle-slider" min="-1" max="1" step="0.05" value="0" oninput="sendLive()">
    </div>
  </section>

  <section class="card">
    <h2>ステアリング校正</h2>
    <p class="card-sub">生のPWM値を送って試し、良い値が見つかったら「確定」する(motor.pyの調整ウィザードと同じ操作)。</p>
    __STEERING_CODE__
    <div class="raw-row">
      <input type="number" id="steering-raw-input" placeholder="例: 430" min="100" max="600">
      <button onclick="testRaw('steering')">送信(テスト)</button>
    </div>
    <div class="lock-buttons">
      <button onclick="lockSteeringCenter()">これを中央にする</button>
      <button onclick="lockSteeringExtreme()">これを左右どちらかの最大にする</button>
    </div>
  </section>

  <section class="card">
    <h2>スロットル校正</h2>
    <p class="card-sub">停止・前進最大・後退最大を、それぞれ個別に確定する。</p>
    __THROTTLE_CODE__
    <div class="raw-row">
      <input type="number" id="throttle-raw-input" placeholder="例: 380" min="100" max="600">
      <button onclick="testRaw('throttle')">送信(テスト)</button>
    </div>
    <div class="lock-buttons">
      <button onclick="lockThrottle('STOPPED')">これを停止(ニュートラル)にする</button>
      <button onclick="lockThrottle('FORWARD')">これを前進最大にする</button>
      <button onclick="lockThrottle('REVERSE')">これを後退最大にする</button>
    </div>
  </section>

  <section class="card">
    <h2>確定した値</h2>
    <p class="card-sub">「config.pyに保存」を押すまでは、まだファイルには書き込まれません。</p>
    <table class="summary" id="summary-table"></table>
  </section>
</main>
<div class="stopbar">
  <button id="stop" onclick="stopAll()">■ 停止</button>
  <span class="path">対象: __CONFIG_PATH__</span>
  <button id="save" onclick="saveToConfig()">config.pyに保存</button>
</div>
<script>
const CURRENT_VALUES = __CURRENT_VALUES__;
const FIELD_LABELS = __FIELD_LABELS__;
const calib = {{
  STEERING_CENTER_PWM: null,
  STEERING_WIDTH_PWM: null,
  THROTTLE_STOPPED_PWM: null,
  THROTTLE_FORWARD_PWM: null,
  THROTTLE_REVERSE_PWM: null,
}};

function showToast(msg, isError) {{
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = isError ? 'show error' : 'show';
  setTimeout(() => {{ t.className = ''; }}, 3200);
}}

function sendLive() {{
  const steering = parseFloat(document.getElementById('steering-slider').value);
  const throttle = parseFloat(document.getElementById('throttle-slider').value);
  document.getElementById('steering-val').textContent = steering.toFixed(2);
  document.getElementById('throttle-val').textContent = throttle.toFixed(2);
  fetch('/test/live', {{
    method: 'POST', headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{steering, throttle}}),
  }}).catch(e => showToast('通信エラー: ' + e, true));
}}

async function stopAll() {{
  document.getElementById('steering-slider').value = 0;
  document.getElementById('throttle-slider').value = 0;
  document.getElementById('steering-val').textContent = '0.00';
  document.getElementById('throttle-val').textContent = '0.00';
  try {{
    await fetch('/stop', {{method: 'POST'}});
    showToast('停止しました', false);
  }} catch (e) {{
    showToast('通信エラー: ' + e, true);
  }}
}}

async function testRaw(axis) {{
  const input = document.getElementById(axis + '-raw-input');
  const value = parseInt(input.value, 10);
  if (!Number.isFinite(value)) {{ showToast('数値を入力してください', true); return; }}
  try {{
    const res = await fetch('/test/raw', {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{axis, value}}),
    }});
    const data = await res.json();
    if (!data.ok) showToast(data.message || '送信に失敗しました', true);
  }} catch (e) {{
    showToast('通信エラー: ' + e, true);
  }}
}}

function lockSteeringCenter() {{
  const v = parseInt(document.getElementById('steering-raw-input').value, 10);
  if (!Number.isFinite(v)) {{ showToast('先に値を送信してテストしてください', true); return; }}
  calib.STEERING_CENTER_PWM = v;
  showToast('ステアリング中央を ' + v + ' に確定しました', false);
  renderSummary();
}}

function lockSteeringExtreme() {{
  const v = parseInt(document.getElementById('steering-raw-input').value, 10);
  if (!Number.isFinite(v)) {{ showToast('先に値を送信してテストしてください', true); return; }}
  if (calib.STEERING_CENTER_PWM === null) {{ showToast('先に中央を確定してください', true); return; }}
  calib.STEERING_WIDTH_PWM = Math.abs(v - calib.STEERING_CENTER_PWM);
  showToast('振れ幅を ' + calib.STEERING_WIDTH_PWM + ' に確定しました', false);
  renderSummary();
}}

function lockThrottle(kind) {{
  const v = parseInt(document.getElementById('throttle-raw-input').value, 10);
  if (!Number.isFinite(v)) {{ showToast('先に値を送信してテストしてください', true); return; }}
  calib['THROTTLE_' + kind + '_PWM'] = v;
  showToast('確定しました: ' + v, false);
  renderSummary();
}}

function renderSummary() {{
  const table = document.getElementById('summary-table');
  const rows = Object.keys(FIELD_LABELS).map(key => {{
    const cur = CURRENT_VALUES[key];
    const now = calib[key];
    const newCell = now === null
      ? '<span class="new-value unset">未確定</span>'
      : `<span class="new-value">${{now}}</span>`;
    return `<tr><td>${{FIELD_LABELS[key]}}<br><code style="font-size:0.72rem;color:var(--muted)">${{key}}</code></td>
      <td>${{cur === null || cur === undefined ? '-' : cur}}</td><td>→</td><td>${{newCell}}</td></tr>`;
  }}).join('');
  table.innerHTML = `<tr><th>項目</th><th>現在値</th><th></th><th>新しい値</th></tr>${{rows}}`;
}}
renderSummary();

async function saveToConfig() {{
  const values = {{}};
  for (const [k, v] of Object.entries(calib)) {{
    if (v !== null) values[k] = v;
  }}
  if (Object.keys(values).length === 0) {{ showToast('確定した値がありません', true); return; }}
  if (!confirm('config.pyに書き込みます。よろしいですか？(直前の内容はバックアップされます)')) return;
  const btn = document.getElementById('save');
  btn.disabled = true;
  try {{
    const res = await fetch('/save', {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{values}}),
    }});
    const data = await res.json();
    if (data.ok) {{
      showToast('保存しました（バックアップ: ' + data.backup + '）', false);
    }} else {{
      showToast(data.message || '保存に失敗しました', true);
    }}
  }} catch (e) {{
    showToast('通信エラー: ' + e, true);
  }} finally {{
    btn.disabled = false;
  }}
}}
</script>
</body>
</html>'''


# ---------------------------------------------------------------------------
# サーバー
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

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

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = render_page().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        try:
            posted = self._read_json_body()

            if self.path == "/test/live":
                steering = max(-1.0, min(1.0, float(posted.get("steering", 0))))
                throttle = max(-1.0, min(1.0, float(posted.get("throttle", 0))))
                motor_instance.set_steering_pwm_value(steering)
                motor_instance.set_throttle_pwm_value(throttle)
                self._send_json(200, dict(ok=True))

            elif self.path == "/test/raw":
                axis = posted.get("axis")
                value = int(posted.get("value"))
                lo, hi = RAW_PWM_RANGE
                if not (lo <= value <= hi):
                    raise ValueError(f"PWM値は{lo}〜{hi}の範囲にしてください")
                if axis == "steering":
                    channel = motor_instance.CHANNEL_STEERING
                elif axis == "throttle":
                    channel = motor_instance.CHANNEL_THROTTLE
                else:
                    raise ValueError(f"不明な軸: {axis}")
                motor_instance.pwm.set_pwm(channel, 0, value)
                self._send_json(200, dict(ok=True))

            elif self.path == "/stop":
                motor_instance.set_steering_pwm_value(0)
                motor_instance.set_throttle_pwm_value(0)
                self._send_json(200, dict(ok=True))

            elif self.path == "/save":
                values = validate_save_values(posted.get("values", {}))
                backup = write_motor_values(values)
                self._send_json(200, dict(ok=True, backup=backup.name))

            else:
                self.send_response(404)
                self.end_headers()

        except ValueError as e:
            self._send_json(400, dict(ok=False, message=str(e)))
        except Exception as e:  # noqa: BLE001
            self._send_json(500, dict(ok=False, message=f"予期しないエラー: {e}"))


def main():
    if not config_editor.CONFIG_PATH.exists():
        raise SystemExit(f"config.py が見つかりません: {config_editor.CONFIG_PATH}")

    init_motor()

    with ThreadingHTTPServer(("0.0.0.0", PORT), Handler) as httpd:
        print("=" * 60)
        print("モーター校正パネル を起動しました")
        print(f"  対象ファイル: {config_editor.CONFIG_PATH}")
        print(f"  モード:        {'実機接続' if HARDWARE_AVAILABLE else 'モック(シミュレーション)'}")
        print(f"  ローカル:      http://localhost:{PORT}")
        print("  Ctrl+C で終了")
        print("=" * 60)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n終了しました")
        finally:
            try:
                motor_instance.cleanup()
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    main()
