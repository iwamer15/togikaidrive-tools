#!/usr/bin/env python3
"""
togikaidrive 設定エディタ
==========================
config.py の中から、機械学習チュートリアルで触ることが多い項目だけを抜き出し、
ブラウザの入力フォームから安全に編集できるようにするローカルツール。

- 標準ライブラリのみで動作(pip install不要。Raspberry Pi / Jetson でもそのまま動く)
- config.py の該当行だけを書き換える(ファイル全体を作り直さない)
- 保存前に必ずバックアップ(config.py.bak.<日時>)を作成する

使い方:
    python3 server.py
    → ブラウザで http://localhost:8899 を開く
    → 同じネットワーク内の他のPCからは http://<このPCのIPアドレス>:8899
"""
from __future__ import annotations

import ast
import json
import re
import shutil
import socket
import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8899
CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "togikaidrive-dev" / "config.py"

# ---------------------------------------------------------------------------
# フィールド定義（ここに追加すればフォームにも自動で増える）
# ---------------------------------------------------------------------------
FIELDS = [
    # --- データ収集 ---
    dict(key="PLAN", category="collect", kind="select", label="走行モード (PLAN)",
         help="データを集める/走らせるときのモード。手動でデータ収集するなら manual、学習済みAIで走らせるなら ai_model。"),
    dict(key="ACTIVE_SENSORS", category="collect", kind="sensors", label="使用センサー (ACTIVE_SENSORS)",
         help="学習に使うデータを取るセンサーを選ぶ。カメラ画像で学習するなら camera_0 を含める。"),
    dict(key="FORWARD_STRAIGHT", category="collect", kind="float", min=-1, max=1, step=0.05, label="直線速度 (FORWARD_STRAIGHT)",
         help="データ収集・手動走行時のまっすぐ進む速さ。0〜1の範囲が目安。"),
    dict(key="FORWARD_CORNER", category="collect", kind="float", min=-1, max=1, step=0.05, label="カーブ速度 (FORWARD_CORNER)",
         help="データ収集・手動走行時のカーブでの速さ。直線速度より少し小さめが目安。"),
    # --- 学習パラメータ ---
    dict(key="EPOCHS", category="train", kind="int", min=1, max=500, label="学習回数 (EPOCHS)",
         help="集めたデータを何周学習させるか。多いほど学習は進むが時間もかかる。まずは30前後が目安。"),
    dict(key="BATCH_SIZE", category="train", kind="int", min=1, max=512, label="バッチサイズ (BATCH_SIZE)",
         help="1回の学習ステップで同時に見せるデータ数。大きいほど学習は安定するが、メモリを多く使う。"),
    dict(key="HIDDEN_DIM", category="train", kind="int", min=1, max=1024, label="隠れ層の大きさ (HIDDEN_DIM)",
         help="ニューラルネットの1層あたりのノード数。大きいほど複雑な運転を学習できるが、過学習しやすくなる。"),
    dict(key="NUM_HIDDEN_LAYERS", category="train", kind="int", min=1, max=20, label="隠れ層の数 (NUM_HIDDEN_LAYERS)",
         help="ニューラルネットの層の深さ。基本は2〜3層で十分。"),
    # --- モデル指定 ---
    dict(key="MODEL_DIR", category="model", kind="str", label="モデル保存フォルダ (MODEL_DIR)",
         help="学習済みモデルを保存・読み込みするフォルダ名。通常は変更不要。"),
    dict(key="MODEL_NAME", category="model", kind="str", label="使用するモデルファイル名 (MODEL_NAME)",
         help="自動走行時に読み込む学習済みモデルのファイル名。train_pytorch.py の実行後に表示される名前をここに入れる。"),
]

CATEGORIES = [
    dict(id="collect", title="データ収集", subtitle="1. 走行モードとセンサーを決めて、手動でデータを集める", icon="📡", accent="cyan"),
    dict(id="train", title="学習パラメータ", subtitle="2. train_pytorch.py で学習させる時の設定", icon="🧠", accent="orange"),
    dict(id="model", title="モデル指定", subtitle="3. 学習済みモデルを自動走行で使う", icon="🤖", accent="steel"),
]

# ---------------------------------------------------------------------------
# config.py の読み書き
# ---------------------------------------------------------------------------
def _line_pattern(key: str) -> re.Pattern:
    # group1: "KEY = "  group2: 値の式  group3: 行末コメント(あれば)
    return re.compile(rf"^([ \t]*{re.escape(key)}\s*=\s*)(.+?)([ \t]*#.*)?$", re.MULTILINE)


def read_plan_list(text: str) -> list[dict]:
    """PLAN_LIST を読み取り、コメント区切りでグループ化した選択肢を作る。"""
    m = re.search(r"PLAN_LIST\s*=\s*\[(.*?)^\]", text, re.MULTILINE | re.DOTALL)
    if not m:
        return [dict(group="", options=[])]
    body = m.group(1)
    groups: list[dict] = []
    current = dict(group="その他", options=[])
    for line in body.splitlines():
        header = re.match(r"\s*#\s*-{2,}\s*(.+?)\s*-{2,}\s*$", line)
        if header:
            current = dict(group=header.group(1), options=[])
            groups.append(current)
            continue
        values = re.findall(r'"([^"]+)"', line)
        if not values:
            continue
        comment_m = re.search(r"#\s*(.+)$", line)
        tip = comment_m.group(1).strip() if (comment_m and len(values) == 1) else ""
        for v in values:
            current["options"].append(dict(value=v, tip=tip))
    if not groups:
        groups = [current]
    return [g for g in groups if g["options"]]


def read_values(text: str) -> dict:
    values = {}
    for f in FIELDS:
        pat = _line_pattern(f["key"])
        m = pat.search(text)
        if not m:
            values[f["key"]] = None
            continue
        raw = m.group(2).strip()
        try:
            values[f["key"]] = ast.literal_eval(raw)
        except Exception:
            values[f["key"]] = raw.strip("\"'")
    return values


def literal_for(kind: str, value) -> str:
    if kind == "str":
        return json.dumps(str(value))
    if kind == "int":
        return str(int(value))
    if kind == "float":
        return str(float(value))
    if kind == "sensors":
        items = [str(v) for v in value if str(v).strip()]
        return "[" + ", ".join(json.dumps(v) for v in items) + "]"
    if kind == "select":
        return json.dumps(str(value))
    raise ValueError(f"unknown kind: {kind}")


def validate(field: dict, value):
    kind = field["kind"]
    key = field["key"]
    if kind == "int":
        try:
            v = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} は整数で入力してください")
        if "min" in field and v < field["min"]:
            raise ValueError(f"{key} は {field['min']} 以上にしてください")
        if "max" in field and v > field["max"]:
            raise ValueError(f"{key} は {field['max']} 以下にしてください")
        return v
    if kind == "float":
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} は数値で入力してください")
        if "min" in field and v < field["min"]:
            raise ValueError(f"{key} は {field['min']} 以上にしてください")
        if "max" in field and v > field["max"]:
            raise ValueError(f"{key} は {field['max']} 以下にしてください")
        return v
    if kind in ("str", "select"):
        v = str(value).strip()
        if not v:
            raise ValueError(f"{key} を入力してください")
        return v
    if kind == "sensors":
        if not isinstance(value, list) or not value:
            raise ValueError("センサーを最低1つ選んでください")
        return [str(v) for v in value]
    raise ValueError(f"unknown kind: {kind}")


def write_values(new_values: dict) -> Path:
    text = CONFIG_PATH.read_text(encoding="utf-8")

    backup_path = CONFIG_PATH.with_name(
        f"config.py.bak.{datetime.datetime.now():%Y%m%d_%H%M%S}"
    )
    shutil.copy2(CONFIG_PATH, backup_path)

    for f in FIELDS:
        key = f["key"]
        if key not in new_values:
            continue
        literal = literal_for(f["kind"], new_values[key])
        pat = _line_pattern(key)

        def repl(m, literal=literal):
            comment = m.group(3) or ""
            return f"{m.group(1)}{literal}{comment}"

        text, n = pat.subn(repl, text, count=1)
        if n == 0:
            raise ValueError(f"config.py 内に {key} の行が見つかりませんでした")

    CONFIG_PATH.write_text(text, encoding="utf-8")
    return backup_path


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
PALETTE = dict(
    navy="#10131A", steel="#1F2A44", steel_soft="#3A4A6B", cyan="#00B4C6",
    orange="#FF4B2B", white="#FFFFFF", card_bg="#F3F5FA", text_dark="#16192A",
    muted="#6B7280", orange_tint="#FFEDE9", cyan_tint="#E4FAFC", steel_tint="#EAEEF6",
)

ACCENT_COLOR = {"cyan": PALETTE["cyan"], "orange": PALETTE["orange"], "steel": PALETTE["steel"]}
ACCENT_TINT = {"cyan": PALETTE["cyan_tint"], "orange": PALETTE["orange_tint"], "steel": PALETTE["steel_tint"]}

SENSOR_OPTIONS = [
    ("ultrasonic", "超音波センサー"),
    ("lidar", "LiDAR"),
    ("gs2", "GS2（近距離ラインセンサー）"),
    ("camera_0", "カメラ 0"),
    ("camera_1", "カメラ 1"),
    ("imu", "IMU（加速度・ジャイロ）"),
    ("optical_flow", "オプティカルフロー"),
    ("rpm", "RPMセンサー"),
]


def render_field(field: dict, value, plan_groups) -> str:
    key = field["key"]
    label = field["label"]
    help_text = field["help"]
    kind = field["kind"]

    if kind == "select":
        options_html = ""
        for group in plan_groups:
            opts = "".join(
                f'<option value="{o["value"]}" title="{o["tip"]}" {"selected" if o["value"] == value else ""}>{o["value"]}</option>'
                for o in group["options"]
            )
            options_html += f'<optgroup label="{group["group"]}">{opts}</optgroup>'
        control = f'<select name="{key}" data-kind="select">{options_html}</select>'
    elif kind == "sensors":
        current = set(value or [])
        boxes = "".join(
            f'''<label class="chk"><input type="checkbox" name="{key}" value="{v}" {"checked" if v in current else ""}>
                <span>{label_ja}</span></label>'''
            for v, label_ja in SENSOR_OPTIONS
        )
        control = f'<div class="chk-group" data-kind="sensors" data-key="{key}">{boxes}</div>'
    elif kind in ("int", "float"):
        step = field.get("step", 1 if kind == "int" else 0.01)
        minv = field.get("min", "")
        maxv = field.get("max", "")
        control = (f'<input type="number" name="{key}" value="{value}" step="{step}" '
                   f'min="{minv}" max="{maxv}" data-kind="{kind}">')
    else:
        control = f'<input type="text" name="{key}" value="{value if value is not None else ""}" data-kind="{kind}">'

    return f'''
    <div class="field">
      <label class="field-label">{label}</label>
      <p class="field-help">{help_text}</p>
      {control}
      <p class="field-error" data-error-for="{key}"></p>
    </div>'''


def render_page() -> str:
    text = CONFIG_PATH.read_text(encoding="utf-8")
    values = read_values(text)
    plan_groups = read_plan_list(text)

    cards = ""
    for cat in CATEGORIES:
        accent = ACCENT_COLOR[cat["accent"]]
        tint = ACCENT_TINT[cat["accent"]]
        fields_html = "".join(
            render_field(f, values.get(f["key"]), plan_groups)
            for f in FIELDS if f["category"] == cat["id"]
        )
        cards += f'''
        <section class="card">
          <div class="card-head">
            <div class="icon-circle" style="background:{tint}">{cat["icon"]}</div>
            <div>
              <h2>{cat["title"]}</h2>
              <p class="card-subtitle">{cat["subtitle"]}</p>
            </div>
          </div>
          <div class="card-body" style="border-color:{accent}22">{fields_html}</div>
        </section>'''

    return HTML_SHELL.replace("__CARDS__", cards).replace("__CONFIG_PATH__", str(CONFIG_PATH))


HTML_SHELL = f'''<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>togikaidrive 設定エディタ</title>
<style>
  :root {{
    --navy: {PALETTE["navy"]}; --steel: {PALETTE["steel"]}; --steel-soft: {PALETTE["steel_soft"]};
    --cyan: {PALETTE["cyan"]}; --orange: {PALETTE["orange"]}; --card-bg: {PALETTE["card_bg"]};
    --text-dark: {PALETTE["text_dark"]}; --muted: {PALETTE["muted"]};
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: #F7F8FB; color: var(--text-dark);
    font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Yu Gothic", "Segoe UI", sans-serif;
    padding-bottom: 6rem;
  }}
  header {{
    background: var(--navy); color: #fff; padding: 2rem 1.5rem 2.4rem;
  }}
  header .eyebrow {{ color: var(--cyan); font-size: 0.75rem; font-weight: 700; letter-spacing: 0.12em; }}
  header h1 {{ margin: 0.3rem 0 0.4rem; font-size: 1.6rem; }}
  header p {{ margin: 0; color: #B9C0D4; font-size: 0.9rem; }}
  main {{ max-width: 760px; margin: -1.4rem auto 0; padding: 0 1.2rem; display: flex; flex-direction: column; gap: 1.1rem; }}
  .card {{
    background: #fff; border-radius: 16px; box-shadow: 0 8px 24px rgba(16,19,26,0.08);
    overflow: hidden;
  }}
  .card-head {{ display: flex; align-items: center; gap: 0.9rem; padding: 1.3rem 1.4rem 1rem; }}
  .icon-circle {{
    width: 44px; height: 44px; border-radius: 50%; display: flex; align-items: center;
    justify-content: center; font-size: 1.3rem; flex-shrink: 0;
  }}
  .card-head h2 {{ margin: 0; font-size: 1.05rem; }}
  .card-subtitle {{ margin: 0.15rem 0 0; color: var(--muted); font-size: 0.82rem; }}
  .card-body {{ padding: 0.2rem 1.4rem 1.3rem; border-top: 1px solid; }}
  .field {{ padding: 0.9rem 0; border-bottom: 1px solid #EEF0F5; }}
  .field:last-child {{ border-bottom: none; }}
  .field-label {{ display: block; font-weight: 700; font-size: 0.92rem; margin-bottom: 0.2rem; }}
  .field-help {{ margin: 0 0 0.5rem; color: var(--muted); font-size: 0.8rem; line-height: 1.4; }}
  .field-error {{ margin: 0.35rem 0 0; color: var(--orange); font-size: 0.78rem; min-height: 1em; }}
  input[type=text], input[type=number], select {{
    width: 100%; padding: 0.55rem 0.7rem; border: 1px solid #D8DCE6; border-radius: 8px;
    font-size: 0.95rem; background: #FBFBFD; color: var(--text-dark);
  }}
  input:focus, select:focus {{ outline: 2px solid var(--cyan); outline-offset: 1px; border-color: var(--cyan); }}
  .chk-group {{ display: flex; flex-wrap: wrap; gap: 0.5rem 1rem; }}
  .chk {{ display: flex; align-items: center; gap: 0.4rem; font-size: 0.88rem; background: #FBFBFD;
    border: 1px solid #D8DCE6; padding: 0.4rem 0.65rem; border-radius: 8px; cursor: pointer; }}
  .chk input {{ accent-color: var(--cyan); }}
  .savebar {{
    position: fixed; left: 0; right: 0; bottom: 0; background: #fff;
    border-top: 1px solid #E4E7F0; padding: 0.9rem 1.2rem; display: flex; align-items: center;
    justify-content: center; gap: 1rem; box-shadow: 0 -6px 18px rgba(16,19,26,0.06);
  }}
  .savebar .path {{ font-size: 0.72rem; color: var(--muted); max-width: 760px; flex: 1; text-align: right;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  button#save {{
    background: var(--orange); color: #fff; border: none; padding: 0.75rem 1.6rem;
    border-radius: 999px; font-size: 0.95rem; font-weight: 700; cursor: pointer;
  }}
  button#save:hover {{ filter: brightness(1.05); }}
  button#save:disabled {{ opacity: 0.6; cursor: default; }}
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
  <div class="eyebrow">TOGIKAIDRIVE · CONFIG EDITOR</div>
  <h1>設定エディタ</h1>
  <p>config.py の機械学習チュートリアル関連項目を、フォームから安全に編集します。</p>
</header>
<div id="toast"></div>
<main id="cards">
__CARDS__
</main>
<div class="savebar">
  <span class="path">対象: __CONFIG_PATH__</span>
  <button id="save">変更を保存</button>
</div>
<script>
function collectValues() {{
  const values = {{}};
  document.querySelectorAll('[data-kind]').forEach(el => {{
    const kind = el.dataset.kind;
    if (kind === 'sensors') {{
      const key = el.dataset.key;
      values[key] = Array.from(el.querySelectorAll('input[type=checkbox]:checked')).map(c => c.value);
    }} else {{
      const key = el.name;
      values[key] = el.value;
    }}
  }});
  return values;
}}

function showToast(msg, isError) {{
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = isError ? 'show error' : 'show';
  setTimeout(() => {{ t.className = ''; }}, 3200);
}}

document.getElementById('save').addEventListener('click', async () => {{
  document.querySelectorAll('.field-error').forEach(e => e.textContent = '');
  const btn = document.getElementById('save');
  btn.disabled = true;
  btn.textContent = '保存中…';
  try {{
    const res = await fetch('/save', {{
      method: 'POST',
      headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify(collectValues()),
    }});
    const data = await res.json();
    if (data.ok) {{
      showToast('保存しました（バックアップ: ' + data.backup + '）', false);
    }} else {{
      showToast(data.message || '保存に失敗しました', true);
      if (data.field) {{
        const errEl = document.querySelector(`[data-error-for="${{data.field}}"]`);
        if (errEl) errEl.textContent = data.message;
      }}
    }}
  }} catch (e) {{
    showToast('通信エラー: ' + e, true);
  }} finally {{
    btn.disabled = false;
    btn.textContent = '変更を保存';
  }}
}});
</script>
</body>
</html>'''


# ---------------------------------------------------------------------------
# サーバー
# ---------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 標準出力を静かに保つ

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
        if self.path != "/save":
            self.send_response(404)
            self.end_headers()
            return
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length)
        try:
            posted = json.loads(raw.decode("utf-8"))
            new_values = {}
            for f in FIELDS:
                key = f["key"]
                if key not in posted:
                    continue
                new_values[key] = validate(f, posted[key])
            backup = write_values(new_values)
            response = dict(ok=True, backup=backup.name)
            status = 200
        except ValueError as e:
            response = dict(ok=False, message=str(e))
            status = 400
        except Exception as e:  # noqa: BLE001
            response = dict(ok=False, message=f"予期しないエラー: {e}")
            status = 500

        body = json.dumps(response).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    if not CONFIG_PATH.exists():
        raise SystemExit(f"config.py が見つかりません: {CONFIG_PATH}")

    with ThreadingHTTPServer(("0.0.0.0", PORT), Handler) as httpd:
        print("=" * 60)
        print("togikaidrive 設定エディタ を起動しました")
        print(f"  対象ファイル: {CONFIG_PATH}")
        print(f"  ローカル:      http://localhost:{PORT}")
        print(f"  同一ネットワーク: http://{local_ip()}:{PORT}")
        print("  Ctrl+C で終了")
        print("=" * 60)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n終了しました")


if __name__ == "__main__":
    main()
