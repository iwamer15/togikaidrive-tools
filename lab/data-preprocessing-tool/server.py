#!/usr/bin/env python3
"""
走行データ前処理ツール
======================
`togikaidrive-dev/data/data_<timestamp>/catalog_*.catalog`(DonkeyCar形式のJSON Lines)を、
ブラウザから可視化・トリミングできるようにするローカルツール。

背景:
    機械学習講座で教えている前処理(手動走行開始前/終了後の不要区間、壁への衝突などの
    外乱区間を取り除く)は、現状SSH越しに`nano`で該当行を目視で探して`Ctrl+K`で消す
    完全な手作業。このツールはそれをブラウザのグラフ+範囲指定に置き換える。

安全設計:
    - `manifest.json`の`deleted_indexes`機構は使わない。train_pytorch.pyの
      load_donkeycar_data()はこの値をカタログファイルごとに0から数え直した位置として
      判定するため、複数catalogファイルにまたがるデータでは意図しない行まで削除扱いに
      なってしまうバグがある(train_pytorch.py側は変更しない)。
    - 代わりに、対象の`catalog_N.catalog`を直接安全に書き換える(講座で教えている
      手動編集と同じ結果になる、より確実な方法)。保存前に必ずバックアップを作成する。
    - `manifest.json`・`images/`ディレクトリには一切手を触れない。
    - 空行・JSONとして壊れている行は、表示・保存どちらでも同じ基準(iter_catalog_lines)
      で「存在しないもの」として扱う(train_pytorch.py側でも読み飛ばされるため)。

使い方:
    python3 server.py
    → ブラウザで http://localhost:8900 を開く
"""
from __future__ import annotations

import datetime
import json
import re
import shutil
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8900
HERE = Path(__file__).resolve().parent
TOOLS_ROOT = HERE.parent  # lab/ (兄弟ツールとshared/がある場所)
REPO_ROOT = TOOLS_ROOT.parent  # ト技会-minicar/ (togikaidrive-dev/ がある場所)

# ポータル(togikaidrive-portal)がタブとして埋め込む際に使うメタ情報
PANEL_ID = "prep"
PANEL_TITLE = "前処理"
PANEL_ICON = "🧹"

# デザイン(PALETTE)とHTMLエスケープは3ツール共通のshared/ui_kit.pyを使う。
sys.path.insert(0, str(TOOLS_ROOT))
from shared import env_check, ui_kit  # noqa: E402
from shared.http_kit import JSONHandlerMixin  # noqa: E402

TOGIKAIDRIVE_DEV_DIR = env_check.require_togikaidrive_dev(REPO_ROOT)
DATA_DIR = TOGIKAIDRIVE_DEV_DIR / "data"

PALETTE = ui_kit.PALETTE
_html_escape = ui_kit.html_escape

SENSOR_PREFIXES = ("ultrasonic/", "lidar/")


# ---------------------------------------------------------------------------
# データ読み書き
# ---------------------------------------------------------------------------
def list_catalog_files(folder_path: Path) -> list[Path]:
    """catalog_N.catalog を N の順にソートして返す。manifest.jsonのpaths順を優先し、
    無ければ(または読めなければ)ファイル名の番号でソートする。"""
    manifest_path = folder_path / "manifest.json"
    if manifest_path.exists():
        try:
            lines = manifest_path.read_text(encoding="utf-8").splitlines()
            catalog_info = json.loads(lines[4])
            paths = [folder_path / p for p in catalog_info.get("paths", [])]
            paths = [p for p in paths if p.exists()]
            if paths:
                return paths
        except Exception:
            pass  # manifestが読めない/形式が想定と違う場合はフォールバック

    def _num(p: Path) -> int:
        m = re.search(r"catalog_(\d+)", p.name)
        return int(m.group(1)) if m else 0

    return sorted(folder_path.glob("catalog_*.catalog"), key=_num)


def iter_catalog_lines(folder_path: Path):
    """(path, raw_line, record_dict, global_index) を順に yield する。
    空行・JSONとして壊れている行はここで読み飛ばし、数えない(表示・保存の両方で
    このジェネレータだけを真実の情報源として使うことで、行番号のズレを防ぐ)。"""
    global_idx = 0
    for path in list_catalog_files(folder_path):
        with path.open("r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.rstrip("\n")
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                yield path, line, rec, global_idx
                global_idx += 1


def read_all_records(folder_path: Path) -> list[dict]:
    records = []
    for path, _line, rec, gidx in iter_catalog_lines(folder_path):
        rec = dict(rec)
        rec["_file"] = path.name
        rec["_global"] = gidx
        records.append(rec)
    return records


def folder_summary(folder_path: Path) -> dict:
    files = list_catalog_files(folder_path)
    total = sum(1 for _ in iter_catalog_lines(folder_path))
    return dict(
        name=folder_path.name,
        total_records=total,
        catalog_count=len(files),
        mtime=folder_path.stat().st_mtime,
    )


def list_data_folders() -> list[dict]:
    if not DATA_DIR.exists():
        return []
    folders = [p for p in DATA_DIR.iterdir() if p.is_dir() and p.name.startswith("data_")]
    folders.sort(key=lambda p: p.name, reverse=True)
    return [folder_summary(p) for p in folders]


def _merge_ranges(ranges) -> list[tuple[int, int]]:
    norm = []
    for r in ranges:
        try:
            start, end = int(r[0]), int(r[1])
        except (TypeError, ValueError, IndexError):
            continue
        start = max(0, start)
        if end <= start:
            continue
        norm.append((start, end))
    norm.sort()
    merged: list[tuple[int, int]] = []
    for start, end in norm:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def _make_backup_for(path: Path) -> Path:
    backup_path = path.with_name(f"{path.name}.bak.{datetime.datetime.now():%Y%m%d_%H%M%S}")
    shutil.copy2(path, backup_path)
    return backup_path


def apply_deletions(folder_name: str, delete_ranges: list) -> dict:
    folder_path = DATA_DIR / folder_name
    if not folder_path.is_dir():
        raise ValueError(f"データフォルダが見つかりません: {folder_name}")

    merged = _merge_ranges(delete_ranges)
    if not merged:
        raise ValueError("削除範囲が指定されていません")

    # ファイルごとに「残す」レコードを集める(iter_catalog_linesと同じ基準で読む)
    kept_by_file: dict[Path, list[dict]] = {}
    original_counts: dict[Path, int] = {}
    for path, _line, rec, gidx in iter_catalog_lines(folder_path):
        original_counts[path] = original_counts.get(path, 0) + 1
        if any(start <= gidx < end for start, end in merged):
            continue
        kept_by_file.setdefault(path, []).append(rec)

    changed_files = []
    for path in list_catalog_files(folder_path):
        original_count = original_counts.get(path, 0)
        kept = kept_by_file.get(path, [])
        if len(kept) == original_count:
            continue  # このファイルは変化なし(バックアップも取らない)

        backup_path = _make_backup_for(path)
        for i, rec in enumerate(kept):
            rec["_index"] = i
        text = "\n".join(json.dumps(rec, ensure_ascii=False) for rec in kept)
        path.write_text(text + ("\n" if text else ""), encoding="utf-8")
        changed_files.append(dict(
            file=path.name, backup=backup_path.name,
            before=original_count, after=len(kept),
        ))

    if not changed_files:
        raise ValueError("削除範囲に該当するレコードがありませんでした")
    return dict(changed_files=changed_files)


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
def render_page() -> str:
    folders = list_data_folders()
    folders_json = json.dumps(folders, ensure_ascii=False)
    return (
        HTML_SHELL
        .replace("__DATA_DIR__", _html_escape(str(DATA_DIR)))
        .replace("__FOLDERS__", folders_json)
    )


HTML_SHELL = f'''<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>走行データ前処理ツール</title>
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
  header h1 {{ margin: 0.3rem 0 0.4rem; font-size: 1.4rem; }}
  header p {{ margin: 0; color: #B9C0D4; font-size: 0.8rem; }}

  main {{ max-width: 900px; margin: 1.2rem auto 0; padding: 0 1.2rem; display: flex; flex-direction: column; gap: 1.1rem; }}
  .card {{ background: #fff; border-radius: 16px; box-shadow: 0 8px 24px rgba(16,19,26,0.08); padding: 1.2rem 1.4rem; }}
  .card h2 {{ margin: 0 0 0.6rem; font-size: 1.05rem; }}
  .card .sub {{ margin: 0 0 1rem; color: var(--muted); font-size: 0.82rem; }}

  .folder-row {{
    display: flex; justify-content: space-between; align-items: center; padding: 0.7rem 0.4rem;
    border-bottom: 1px solid #EEF0F5; cursor: pointer; border-radius: 8px;
  }}
  .folder-row:hover {{ background: var(--card-bg); }}
  .folder-row.active {{ background: var(--orange-tint); }}
  .folder-row:last-child {{ border-bottom: none; }}
  .folder-name {{ font-weight: 700; font-size: 0.88rem; }}
  .folder-meta {{ color: var(--muted); font-size: 0.76rem; }}
  .folder-count {{ font-size: 0.82rem; color: var(--text-dark); white-space: nowrap; }}

  #viewer {{ display: none; flex-direction: column; gap: 1.1rem; }}
  #viewer.active {{ display: flex; }}

  .stat-row {{ display: flex; gap: 1.2rem; font-size: 0.85rem; margin-bottom: 0.8rem; flex-wrap: wrap; }}
  .stat-row b {{ color: var(--orange); }}

  svg.chart {{ width: 100%; height: auto; background: var(--navy); border-radius: 10px; }}
  .chart-legend {{ display: flex; gap: 0.9rem; flex-wrap: wrap; margin-top: 0.5rem; font-size: 0.76rem; color: var(--muted); }}
  .chart-legend span {{ display: inline-flex; align-items: center; gap: 0.3rem; }}
  .chart-legend i {{ width: 10px; height: 10px; border-radius: 2px; display: inline-block; }}

  .trim-row {{ display: flex; gap: 0.6rem; align-items: flex-end; flex-wrap: wrap; margin-bottom: 0.8rem; }}
  .trim-row .field {{ display: flex; flex-direction: column; gap: 0.25rem; }}
  .trim-row label {{ font-size: 0.76rem; color: var(--muted); }}
  .trim-row input[type=number] {{
    width: 9rem; padding: 0.5rem 0.6rem; border: 1px solid #D8DCE6; border-radius: 8px; font-size: 0.9rem;
  }}
  .trim-row button, .range-row button {{
    background: var(--steel); color: #fff; border: none; padding: 0.55rem 0.9rem; border-radius: 8px;
    font-size: 0.82rem; font-weight: 700; cursor: pointer; white-space: nowrap;
  }}

  table.ranges {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; margin-top: 0.6rem; }}
  table.ranges th {{ text-align: left; color: var(--muted); font-weight: 700; font-size: 0.75rem; padding: 0.3rem 0.4rem; }}
  table.ranges td {{ padding: 0.4rem; border-top: 1px solid #EEF0F5; }}
  table.ranges button.danger {{
    background: none; border: 1px solid var(--orange); color: var(--orange); padding: 0.25rem 0.6rem;
    border-radius: 6px; font-size: 0.72rem; cursor: pointer;
  }}

  .preview-box {{
    background: var(--orange-tint); border-radius: 10px; padding: 0.8rem 1rem; font-size: 0.88rem; margin-top: 0.8rem;
  }}
  .preview-box b {{ color: var(--orange); }}

  .savebar {{
    position: fixed; left: 0; right: 0; bottom: 0; background: #fff; border-top: 1px solid #E4E7F0;
    padding: 0.9rem 1.2rem; display: flex; align-items: center; justify-content: center; gap: 1rem;
    box-shadow: 0 -6px 18px rgba(16,19,26,0.06);
  }}
  .savebar .path {{ font-size: 0.68rem; color: var(--muted); flex: 1; text-align: right; overflow: hidden;
    text-overflow: ellipsis; white-space: nowrap; }}
  button#save-btn {{
    background: var(--orange); color: #fff; border: none; padding: 0.7rem 1.4rem; border-radius: 999px;
    font-size: 0.95rem; font-weight: 700; cursor: pointer;
  }}
  button#save-btn:disabled {{ opacity: 0.5; cursor: default; }}
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
  <div class="eyebrow">TOGIKAIDRIVE · DATA PREPROCESSING</div>
  <h1>走行データ前処理ツール</h1>
  <p>手動走行で集めたデータの不要区間を、グラフを見ながら安全にトリミングします。</p>
</header>
<div id="toast"></div>
<main>
  <div class="card" id="folder-card">
    <h2>📁 データフォルダ</h2>
    <p class="sub">対象: __DATA_DIR__</p>
    <div id="folder-list"></div>
  </div>

  <div id="viewer">
    <div class="card">
      <h2 id="viewer-title">-</h2>
      <div class="stat-row">
        <span>現在の総レコード数: <b id="stat-total">-</b></span>
        <span>カタログファイル数: <b id="stat-files">-</b></span>
      </div>
      <svg id="chart-motion" class="chart" viewBox="0 0 1000 220"></svg>
      <div class="chart-legend">
        <span><i style="background:#00B4C6"></i>steering</span>
        <span><i style="background:#FF4B2B"></i>throttle</span>
      </div>
      <svg id="chart-sensor" class="chart" viewBox="0 0 1000 220" style="margin-top:0.8rem;"></svg>
      <div class="chart-legend" id="sensor-legend"></div>
      <p class="sub" style="margin-top:0.6rem;">オレンジの帯は、下で指定した削除範囲のプレビューです。</p>
    </div>

    <div class="card">
      <h2>✂️ トリミング</h2>
      <p class="sub">講座で教えている「先頭/末尾の不要区間を削除」と同じ操作です。番号はグラフの横軸(通し番号)に対応します。</p>
      <div class="trim-row">
        <div class="field">
          <label>先頭を削除(0 〜 この番号の手前まで)</label>
          <input type="number" id="head-trim-input" min="0" placeholder="例: 30">
        </div>
        <button type="button" onclick="addHeadTrim()">先頭トリムを追加</button>
      </div>
      <div class="trim-row">
        <div class="field">
          <label>末尾を削除(この番号 〜 最後まで)</label>
          <input type="number" id="tail-trim-input" min="0" placeholder="例: 3700">
        </div>
        <button type="button" onclick="addTailTrim()">末尾トリムを追加</button>
      </div>
      <div class="trim-row range-row">
        <div class="field">
          <label>途中の範囲を削除(開始番号)</label>
          <input type="number" id="range-start-input" min="0" placeholder="例: 500">
        </div>
        <div class="field">
          <label>途中の範囲を削除(終了番号、この手前まで)</label>
          <input type="number" id="range-end-input" min="0" placeholder="例: 520">
        </div>
        <button type="button" onclick="addRange()">この範囲を追加</button>
      </div>

      <table class="ranges" id="ranges-table"></table>

      <div class="preview-box" id="preview-box">まだ削除範囲がありません</div>
    </div>
  </div>
</main>
<div class="savebar">
  <span class="path" id="target-path">対象フォルダ未選択</span>
  <button id="save-btn" onclick="saveDeletions()" disabled>この内容でカタログファイルを書き換える</button>
</div>
<script>
const FOLDERS = __FOLDERS__;
let CURRENT_FOLDER = null;
let RECORDS = [];
let DELETE_RANGES = []; // [start, end) のペアの配列

function showToast(msg, isError) {{
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = isError ? 'show error' : 'show';
  setTimeout(() => {{ t.className = ''; }}, 3200);
}}

function fmtBytes(n) {{ return n.toLocaleString('ja-JP'); }}

function renderFolderList() {{
  const box = document.getElementById('folder-list');
  if (!FOLDERS.length) {{
    box.innerHTML = '<p class="sub">データフォルダが見つかりません。</p>';
    return;
  }}
  box.innerHTML = FOLDERS.map(f => `
    <div class="folder-row" data-name="${{f.name}}" onclick="selectFolder('${{f.name}}')">
      <div>
        <div class="folder-name">${{f.name}}</div>
        <div class="folder-meta">catalogファイル ${{f.catalog_count}}個</div>
      </div>
      <div class="folder-count">${{fmtBytes(f.total_records)}} レコード</div>
    </div>
  `).join('');
}}
renderFolderList();

async function selectFolder(name) {{
  document.querySelectorAll('.folder-row').forEach(el => el.classList.toggle('active', el.dataset.name === name));
  try {{
    const res = await fetch('/api/records?folder=' + encodeURIComponent(name));
    const data = await res.json();
    if (!data.ok) {{ showToast(data.message || '読み込みに失敗しました', true); return; }}
    CURRENT_FOLDER = name;
    RECORDS = data.records;
    DELETE_RANGES = [];
    document.getElementById('viewer').classList.add('active');
    document.getElementById('viewer-title').textContent = name;
    document.getElementById('stat-total').textContent = RECORDS.length;
    document.getElementById('stat-files').textContent = data.catalog_count;
    document.getElementById('target-path').textContent = '対象: ' + name;
    document.getElementById('save-btn').disabled = true;
    drawCharts();
    renderRanges();
  }} catch (e) {{
    showToast('通信エラー: ' + e, true);
  }}
}}

// ---------------------------------------------------------------------
// チャート(外部ライブラリなし、手書きSVG折れ線)
// ---------------------------------------------------------------------
const SENSOR_COLORS = ['#00B4C6', '#FF4B2B', '#3A4A6B', '#8B5CF6', '#22C55E'];

function downsample(arr, maxPoints) {{
  if (arr.length <= maxPoints) return arr.map((v, i) => [i, v]);
  const step = arr.length / maxPoints;
  const out = [];
  for (let i = 0; i < maxPoints; i++) {{
    const idx = Math.floor(i * step);
    out.push([idx, arr[idx]]);
  }}
  return out;
}}

function buildPolyline(points, xMax, yMin, yMax, w, h) {{
  return points.map(([x, y]) => {{
    const px = (x / Math.max(xMax, 1)) * w;
    const py = h - ((y - yMin) / Math.max(yMax - yMin, 1e-9)) * h;
    return `${{px.toFixed(1)}},${{py.toFixed(1)}}`;
  }}).join(' ');
}}

function drawCharts() {{
  const n = RECORDS.length;
  const w = 1000, h = 220;

  // --- steering / throttle ---
  const steering = RECORDS.map(r => r['user/angle'] ?? 0);
  const throttle = RECORDS.map(r => r['user/throttle'] ?? 0);
  const motionSvg = document.getElementById('chart-motion');
  const sPts = buildPolyline(downsample(steering, 600), n, -1, 1, w, h);
  const tPts = buildPolyline(downsample(throttle, 600), n, -1, 1, w, h);
  motionSvg.innerHTML =
    deleteRangeRects(n, w, h) +
    `<polyline points="${{sPts}}" fill="none" stroke="#00B4C6" stroke-width="1.5"/>` +
    `<polyline points="${{tPts}}" fill="none" stroke="#FF4B2B" stroke-width="1.5"/>`;

  // --- センサー距離 ---
  const sensorKeys = new Set();
  for (const r of RECORDS) {{
    for (const k in r) {{
      if (k.startsWith('ultrasonic/') || k.startsWith('lidar/')) sensorKeys.add(k);
    }}
  }}
  const keys = Array.from(sensorKeys).sort();
  const sensorSvg = document.getElementById('chart-sensor');
  let sensorHtml = deleteRangeRects(n, w, h);
  keys.forEach((key, i) => {{
    const values = RECORDS.map(r => r[key] ?? 0);
    const pts = buildPolyline(downsample(values, 600), n, 0, 2000, w, h);
    const color = SENSOR_COLORS[i % SENSOR_COLORS.length];
    sensorHtml += `<polyline points="${{pts}}" fill="none" stroke="${{color}}" stroke-width="1.2" opacity="0.9"/>`;
  }});
  sensorSvg.innerHTML = sensorHtml;
  document.getElementById('sensor-legend').innerHTML = keys.map((key, i) =>
    `<span><i style="background:${{SENSOR_COLORS[i % SENSOR_COLORS.length]}}"></i>${{key}}</span>`
  ).join('');
}}

function mergeRanges(ranges) {{
  const norm = ranges.map(([s, e]) => [Math.max(0, s), e]).filter(([s, e]) => e > s);
  norm.sort((a, b) => a[0] - b[0]);
  const merged = [];
  for (const [s, e] of norm) {{
    if (merged.length && s <= merged[merged.length - 1][1]) {{
      merged[merged.length - 1][1] = Math.max(merged[merged.length - 1][1], e);
    }} else {{
      merged.push([s, e]);
    }}
  }}
  return merged;
}}

function deleteRangeRects(n, w, h) {{
  const merged = mergeRanges(DELETE_RANGES);
  return merged.map(([s, e]) => {{
    const x = (s / Math.max(n, 1)) * w;
    const rw = ((e - s) / Math.max(n, 1)) * w;
    return `<rect x="${{x.toFixed(1)}}" y="0" width="${{Math.max(rw, 1).toFixed(1)}}" height="${{h}}" fill="#FF4B2B" opacity="0.25"/>`;
  }}).join('');
}}

// ---------------------------------------------------------------------
// 削除範囲の管理
// ---------------------------------------------------------------------
function addHeadTrim() {{
  const v = parseInt(document.getElementById('head-trim-input').value, 10);
  if (!Number.isFinite(v) || v <= 0) {{ showToast('1以上の番号を入力してください', true); return; }}
  DELETE_RANGES.push([0, v]);
  afterRangeChange();
}}

function addTailTrim() {{
  const v = parseInt(document.getElementById('tail-trim-input').value, 10);
  if (!Number.isFinite(v) || v < 0 || v >= RECORDS.length) {{ showToast('総レコード数未満の番号を入力してください', true); return; }}
  DELETE_RANGES.push([v, RECORDS.length]);
  afterRangeChange();
}}

function addRange() {{
  const s = parseInt(document.getElementById('range-start-input').value, 10);
  const e = parseInt(document.getElementById('range-end-input').value, 10);
  if (!Number.isFinite(s) || !Number.isFinite(e) || e <= s) {{ showToast('開始 < 終了 になるよう入力してください', true); return; }}
  DELETE_RANGES.push([s, e]);
  afterRangeChange();
}}

function removeRange(idx) {{
  DELETE_RANGES.splice(idx, 1);
  afterRangeChange();
}}

function afterRangeChange() {{
  renderRanges();
  drawCharts();
  updatePreview();
}}

function renderRanges() {{
  const table = document.getElementById('ranges-table');
  if (!DELETE_RANGES.length) {{
    table.innerHTML = '';
    return;
  }}
  const rows = DELETE_RANGES.map((r, i) => `
    <tr><td>${{r[0]}} 〜 ${{r[1] - 1}}</td><td>${{r[1] - r[0]}}件</td>
      <td><button class="danger" onclick="removeRange(${{i}})">削除</button></td></tr>
  `).join('');
  table.innerHTML = `<tr><th>範囲</th><th>件数</th><th></th></tr>${{rows}}`;
}}

function updatePreview() {{
  const box = document.getElementById('preview-box');
  const saveBtn = document.getElementById('save-btn');
  if (!DELETE_RANGES.length) {{
    box.textContent = 'まだ削除範囲がありません';
    saveBtn.disabled = true;
    return;
  }}
  const merged = mergeRanges(DELETE_RANGES);
  const deleteCount = merged.reduce((sum, [s, e]) => sum + (e - s), 0);
  const after = RECORDS.length - deleteCount;
  box.innerHTML = `現在 <b>${{RECORDS.length}}</b>件 → 削除後 <b>${{after}}</b>件(${{deleteCount}}件削除)`;
  saveBtn.disabled = false;
}}

async function saveDeletions() {{
  if (!CURRENT_FOLDER || !DELETE_RANGES.length) return;
  if (!confirm('指定した範囲を削除してcatalogファイルを書き換えます。直前の内容はバックアップされます。よろしいですか？')) return;
  const btn = document.getElementById('save-btn');
  btn.disabled = true;
  try {{
    const res = await fetch('/api/save', {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{folder: CURRENT_FOLDER, delete_ranges: DELETE_RANGES}}),
    }});
    const data = await res.json();
    if (data.ok) {{
      showToast('保存しました(' + data.changed_files.length + 'ファイル書き換え)', false);
      selectFolder(CURRENT_FOLDER); // 最新の内容で読み直す
    }} else {{
      showToast(data.message || '保存に失敗しました', true);
      btn.disabled = false;
    }}
  }} catch (e) {{
    showToast('通信エラー: ' + e, true);
    btn.disabled = false;
  }}
}}
</script>
</body>
</html>'''


# ---------------------------------------------------------------------------
# サーバー
# handle_get/handle_postはこのツール単体のサーバーからも、togikaidrive-portalから
# 埋め込まれた場合からも同じ形で呼べる(戻り値Trueならこのツールが処理済み)。
# ---------------------------------------------------------------------------
def handle_get(handler, path: str) -> bool:
    if path.startswith("/api/records"):
        from urllib.parse import urlparse, parse_qs
        qs = parse_qs(urlparse(path).query)
        folder = (qs.get("folder") or [""])[0]
        folder_path = DATA_DIR / folder
        if not folder or not folder_path.is_dir():
            handler._send_json(400, dict(ok=False, message="データフォルダが見つかりません"))
            return True
        records = read_all_records(folder_path)
        catalog_count = len(list_catalog_files(folder_path))
        handler._send_json(200, dict(ok=True, folder=folder, records=records, catalog_count=catalog_count))
        return True
    return False


def handle_post(handler, path: str, posted: dict) -> bool:
    if path == "/api/save":
        result = apply_deletions(posted.get("folder", ""), posted.get("delete_ranges", []))
        handler._send_json(200, dict(ok=True, **result))
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
    if not DATA_DIR.exists():
        raise SystemExit(f"データディレクトリが見つかりません: {DATA_DIR}")

    with ThreadingHTTPServer(("0.0.0.0", PORT), Handler) as httpd:
        print("=" * 60)
        print("走行データ前処理ツール を起動しました")
        print(f"  対象ディレクトリ: {DATA_DIR}")
        print(f"  ローカル:      http://localhost:{PORT}")
        print("  Ctrl+C で終了")
        print("=" * 60)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n終了しました")


if __name__ == "__main__":
    main()
