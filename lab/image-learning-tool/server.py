#!/usr/bin/env python3
"""
画像学習パネル
==============
画像ベースのモデル学習(YOLO/走行モデル等)はGoogle Colabで実行する運用のため、
このツールはColab学習の「実行導線」と、Colab側の結果をローカルにマージ済みの
MLflow実験記録(`mlruns/`)を見るための「学習分析」を提供する薄いツール。

実行そのもの(データセット選択・Google Driveへの転送・Colabノートブック起動・
学習済みモデル/mlrunsの取り込み)は、既存のアノテーションツール
(`togikaidrive-dev/annotation_training_d2j/main.py`のCloudメニュー)で
既に完成しているため、ここでは再実装しない。このツールは
`shared/app_launcher.py`でそのツールを起動するボタンと、
`shared/mlflow_reader.py`で`mlruns/`を直接読んで表示するグラフだけを持つ。

使い方:
    python3 server.py
    → ブラウザで http://localhost:8903 を開く
"""
from __future__ import annotations

import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

PORT = 8903
HERE = Path(__file__).resolve().parent
TOOLS_ROOT = HERE.parent  # lab/ (兄弟ツールとshared/がある場所)
REPO_ROOT = TOOLS_ROOT.parent  # ト技会-minicar/ (togikaidrive-dev/ がある場所)

# ポータル(togikaidrive-portal)がconfig-editorへ埋め込む際に使うメタ情報
PANEL_ID = "image_learning"
PANEL_TITLE = "画像学習"
PANEL_ICON = "📸"

sys.path.insert(0, str(TOOLS_ROOT))
from shared import ui_kit  # noqa: E402
from shared import app_launcher  # noqa: E402
from shared import mlflow_reader  # noqa: E402
from shared.http_kit import JSONHandlerMixin  # noqa: E402

PALETTE = ui_kit.PALETTE
_html_escape = ui_kit.html_escape

_SAFE_ID = re.compile(r"^[A-Za-z0-9_.\-]+$")


# ---------------------------------------------------------------------------
# mlruns/ の読み取り
# ---------------------------------------------------------------------------
def build_tree() -> list[dict]:
    """実験→run一覧を、メトリクス名・パラメータ付きで返す(グラフの実データは含まない。
    実データは選択されたrunだけを/image_learning/metricで別途取得する)。"""
    tree = []
    for exp in mlflow_reader.list_experiments():
        runs = []
        for run in mlflow_reader.list_runs(Path(exp["path"])):
            run_dir = Path(run["path"])
            runs.append(dict(
                run_id=run["run_id"],
                run_name=run["run_name"],
                status=run["status"],
                start_time=run["start_time"],
                params=mlflow_reader.list_params(run_dir),
                metric_names=mlflow_reader.list_metric_names(run_dir),
            ))
        tree.append(dict(experiment_id=exp["experiment_id"], name=exp["name"], runs=runs))
    return tree


def _find_run_dir(experiment_id: str, run_id: str) -> Path | None:
    if not (_SAFE_ID.match(experiment_id or "") and _SAFE_ID.match(run_id or "")):
        return None
    candidate = mlflow_reader.DEFAULT_MLRUNS_DIR / experiment_id / run_id
    return candidate if candidate.is_dir() else None


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
def render_page() -> str:
    tree = build_tree()
    status = app_launcher.launch_status()
    return (
        HTML_SHELL
        .replace("__TREE__", json.dumps(tree, ensure_ascii=False))
        .replace("__AVAILABLE__", "true" if app_launcher.annotation_tool_available() else "false")
        .replace("__STATUS_RUNNING__", "true" if status["running"] else "false")
        .replace("__MLRUNS_PATH__", _html_escape(str(mlflow_reader.DEFAULT_MLRUNS_DIR)))
    )


HTML_SHELL = f'''<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>画像学習パネル</title>
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

  main {{ max-width: 960px; margin: 1.2rem auto 0; padding: 0 1.2rem; display: flex; flex-direction: column; gap: 1.1rem; }}
  .card {{ background: #fff; border-radius: 16px; box-shadow: 0 8px 24px rgba(16,19,26,0.08); padding: 1.2rem 1.4rem; }}
  .card h2 {{ margin: 0 0 0.6rem; font-size: 1.05rem; }}
  .card .sub {{ margin: 0 0 1rem; color: var(--muted); font-size: 0.82rem; line-height: 1.6; }}

  button.primary {{
    background: var(--orange); color: #fff; border: none; padding: 0.7rem 1.4rem; border-radius: 999px;
    font-size: 0.95rem; font-weight: 700; cursor: pointer;
  }}
  button.primary:disabled {{ opacity: 0.5; cursor: default; }}
  .status-row {{ display: flex; align-items: center; gap: 0.6rem; margin-top: 0.8rem; font-size: 0.85rem; }}
  .status-dot {{ width: 10px; height: 10px; border-radius: 50%; background: var(--muted); }}
  .status-dot.running {{ background: #0F5132; }}

  ol.steps {{ margin: 0 0 0; padding-left: 1.2rem; font-size: 0.82rem; color: var(--muted); line-height: 1.8; }}

  .imgl-field {{ margin-bottom: 0.8rem; }}
  .imgl-field label {{ display: block; font-weight: 700; font-size: 0.85rem; margin-bottom: 0.3rem; }}
  .imgl-field select {{ width: 100%; padding: 0.5rem 0.6rem; border: 1px solid #D8DCE6; border-radius: 8px; font-size: 0.9rem; }}

  .stat-row {{ display: flex; flex-wrap: wrap; gap: 0.7rem; margin-bottom: 1rem; }}
  .stat-chip {{ background: var(--card-bg); border-radius: 10px; padding: 0.6rem 0.9rem; font-size: 0.8rem; }}
  .stat-chip b {{ display: block; font-size: 1.05rem; }}

  table.params {{ width: 100%; border-collapse: collapse; font-size: 0.78rem; margin-top: 0.6rem; }}
  table.params td {{ padding: 0.28rem 0.3rem; border-top: 1px solid #EEF0F5; }}
  table.params td:first-child {{ color: var(--muted); width: 45%; }}

  svg.chart {{ width: 100%; height: auto; background: var(--navy); border-radius: 10px; }}
  .legend {{ display: flex; flex-wrap: wrap; gap: 0.8rem; margin-top: 0.5rem; font-size: 0.76rem; color: var(--muted); }}
  .legend span {{ display: inline-flex; align-items: center; gap: 0.35rem; }}
  .legend i {{ width: 10px; height: 10px; border-radius: 2px; display: inline-block; }}

  .empty {{ color: var(--muted); font-size: 0.85rem; padding: 1rem 0; }}

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
  <div class="eyebrow">TOGIKAIDRIVE · IMAGE LEARNING</div>
  <h1>📸 画像学習パネル</h1>
  <p>画像ベースのモデル学習はGoogle Colabで実行します。ここでは実行の入口と、結果の分析だけを行います。</p>
</header>
<div id="toast"></div>
<main>
  <div class="card">
    <h2>▶️ Colabで学習する</h2>
    <p class="sub">データセットの選択・Google Driveへの転送・Colabノートブックの起動・学習済みモデルの取り込みは、アノテーションツールのCloudメニューから行います。</p>
    <ol class="steps">
      <li>下のボタンでアノテーションツールを起動</li>
      <li>Cloudメニュー → Google Colab → 「転送」でデータセットをアップロード</li>
      <li>生成されたColabノートブックを開いて学習を実行</li>
      <li>学習完了後、同じCloudメニューから学習済みモデル・実験記録(mlruns)をダウンロード</li>
    </ol>
    <button class="primary" id="imgl-launch-btn" onclick="imglLaunchTool()" style="margin-top:1rem;">アノテーションツールを起動</button>
    <div class="status-row">
      <span class="status-dot" id="imgl-status-dot"></span>
      <span id="imgl-status-text">状態を確認中...</span>
    </div>
  </div>

  <div class="card">
    <h2>📊 学習分析</h2>
    <p class="sub">アノテーションツールがGoogle Driveから取り込んだ実験記録(<code>__MLRUNS_PATH__</code>)を表示します。</p>
    <div id="imgl-analysis-empty" class="empty" style="display:none;">まだ実験記録がありません。Colabでの学習後、アノテーションツールで取り込んでください。</div>
    <div id="imgl-analysis-body">
      <div class="imgl-field">
        <label>実験</label>
        <select id="imgl-experiment-select" onchange="imglOnExperimentChange()"></select>
      </div>
      <div class="imgl-field">
        <label>run</label>
        <select id="imgl-run-select" onchange="imglOnRunChange()"></select>
      </div>
      <div id="imgl-stat-row" class="stat-row"></div>
      <svg id="imgl-chart-metrics" class="chart" viewBox="0 0 1000 240"></svg>
      <div id="imgl-chart-legend" class="legend"></div>
      <table class="params" id="imgl-params-table"></table>
    </div>
  </div>
</main>
<script>
const TREE = __TREE__;
const IMGL_AVAILABLE = __AVAILABLE__;
let IMGL_RUNNING = __STATUS_RUNNING__;
const IMGL_COLORS = ['#00B4C6', '#FF4B2B', '#8A6DFF', '#FFC24B', '#4BD37B'];

function showToast(msg, isError) {{
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = isError ? 'show error' : 'show';
  setTimeout(() => {{ t.className = ''; }}, 3200);
}}

function imglRenderLaunchStatus() {{
  const dot = document.getElementById('imgl-status-dot');
  const text = document.getElementById('imgl-status-text');
  const btn = document.getElementById('imgl-launch-btn');
  if (!IMGL_AVAILABLE) {{
    text.textContent = 'アノテーションツールが見つかりません';
    btn.disabled = true;
    return;
  }}
  dot.classList.toggle('running', IMGL_RUNNING);
  text.textContent = IMGL_RUNNING ? '起動中' : '停止中';
}}
imglRenderLaunchStatus();

async function imglLaunchTool() {{
  try {{
    const res = await fetch('/annotation/launch', {{method: 'POST'}});
    const data = await res.json();
    if (!data.ok) {{ showToast(data.message || '起動に失敗しました', true); return; }}
    IMGL_RUNNING = true;
    imglRenderLaunchStatus();
    showToast(data.already_running ? '既に起動しています' : 'アノテーションツールを起動しました', false);
  }} catch (e) {{
    showToast('通信エラー: ' + e, true);
  }}
}}

function imglPopulateExperiments() {{
  const sel = document.getElementById('imgl-experiment-select');
  if (!TREE.length) {{
    document.getElementById('imgl-analysis-empty').style.display = 'block';
    document.getElementById('imgl-analysis-body').style.display = 'none';
    return;
  }}
  sel.innerHTML = TREE.map(e => `<option value="${{e.experiment_id}}">${{escapeHtml(e.name)}} (${{e.runs.length}}件)</option>`).join('');
  imglOnExperimentChange();
}}

function escapeHtml(s) {{
  const div = document.createElement('div');
  div.textContent = String(s);
  return div.innerHTML;
}}

function imglCurrentExperiment() {{
  const id = document.getElementById('imgl-experiment-select').value;
  return TREE.find(e => e.experiment_id === id);
}}

function imglOnExperimentChange() {{
  const exp = imglCurrentExperiment();
  const sel = document.getElementById('imgl-run-select');
  if (!exp || !exp.runs.length) {{
    sel.innerHTML = '<option value="">(runがありません)</option>';
    imglRenderStats(null);
    return;
  }}
  sel.innerHTML = exp.runs.map(r => `<option value="${{r.run_id}}">${{escapeHtml(r.run_name)}}</option>`).join('');
  imglOnRunChange();
}}

function imglCurrentRun() {{
  const exp = imglCurrentExperiment();
  if (!exp) return null;
  const id = document.getElementById('imgl-run-select').value;
  return exp.runs.find(r => r.run_id === id) || null;
}}

async function imglOnRunChange() {{
  const run = imglCurrentRun();
  imglRenderStats(run);
  imglRenderParams(run);
  if (!run) {{ imglRenderChart([]); return; }}

  const exp = imglCurrentExperiment();
  const curveNames = run.metric_names.filter(n => !n.startsWith('final_') && !n.startsWith('best_'));
  const series = [];
  for (const name of curveNames) {{
    try {{
      const res = await fetch(`/image_learning/metric?experiment_id=${{encodeURIComponent(exp.experiment_id)}}&run_id=${{encodeURIComponent(run.run_id)}}&metric=${{encodeURIComponent(name)}}`);
      const points = await res.json();
      if (points.length > 1) series.push({{name, points}});
    }} catch (e) {{ /* このメトリクスだけスキップ */ }}
  }}
  imglRenderChart(series);
}}

function imglRenderStats(run) {{
  const row = document.getElementById('imgl-stat-row');
  if (!run) {{ row.innerHTML = ''; return; }}
  const scalarNames = run.metric_names.filter(n => n.startsWith('final_') || n.startsWith('best_'));
  if (!scalarNames.length) {{ row.innerHTML = ''; return; }}
  row.innerHTML = '<span class="empty" style="padding:0;">読み込み中...</span>';
  Promise.all(scalarNames.map(name =>
    fetch(`/image_learning/metric?experiment_id=${{encodeURIComponent(imglCurrentExperiment().experiment_id)}}&run_id=${{encodeURIComponent(run.run_id)}}&metric=${{encodeURIComponent(name)}}`)
      .then(r => r.json()).then(points => ({{name, value: points.length ? points[points.length - 1].value : null}}))
  )).then(results => {{
    row.innerHTML = results.filter(r => r.value !== null).map(r =>
      `<div class="stat-chip">${{escapeHtml(r.name)}}<b>${{r.value.toFixed(4)}}</b></div>`
    ).join('');
  }});
}}

function imglRenderParams(run) {{
  const table = document.getElementById('imgl-params-table');
  if (!run || !Object.keys(run.params).length) {{ table.innerHTML = ''; return; }}
  table.innerHTML = Object.entries(run.params).map(([k, v]) =>
    `<tr><td>${{escapeHtml(k)}}</td><td>${{escapeHtml(v)}}</td></tr>`
  ).join('');
}}

function imglBuildPolyline(points, xMax, yMin, yMax, w, h) {{
  return points.map(([x, y]) => {{
    const px = (x / Math.max(xMax, 1)) * w;
    const py = h - ((y - yMin) / Math.max(yMax - yMin, 1e-9)) * h;
    return `${{px.toFixed(1)}},${{py.toFixed(1)}}`;
  }}).join(' ');
}}

function imglRenderChart(series) {{
  const svg = document.getElementById('imgl-chart-metrics');
  const legend = document.getElementById('imgl-chart-legend');
  if (!series.length) {{ svg.innerHTML = ''; legend.innerHTML = ''; return; }}
  const w = 1000, h = 240;
  const allValues = series.flatMap(s => s.points.map(p => p.value));
  const yMin = Math.min(...allValues), yMax = Math.max(...allValues);
  const xMax = Math.max(...series.map(s => s.points.length - 1));
  svg.innerHTML = series.map((s, i) => {{
    const pts = s.points.map(p => [p.step, p.value]);
    const color = IMGL_COLORS[i % IMGL_COLORS.length];
    return `<polyline points="${{imglBuildPolyline(pts, xMax, yMin, yMax, w, h)}}" fill="none" stroke="${{color}}" stroke-width="1.6"/>`;
  }}).join('');
  legend.innerHTML = series.map((s, i) =>
    `<span><i style="background:${{IMGL_COLORS[i % IMGL_COLORS.length]}}"></i>${{escapeHtml(s.name)}}</span>`
  ).join('');
}}

imglPopulateExperiments();
</script>
</body>
</html>'''


# ---------------------------------------------------------------------------
# サーバー
# ---------------------------------------------------------------------------
def handle_get(handler, path: str) -> bool:
    if path.startswith("/image_learning/metric"):
        qs = parse_qs(urlparse(path).query)
        experiment_id = (qs.get("experiment_id") or [""])[0]
        run_id = (qs.get("run_id") or [""])[0]
        metric = (qs.get("metric") or [""])[0]
        run_dir = _find_run_dir(experiment_id, run_id)
        if run_dir is None or not _SAFE_ID.match(metric or ""):
            handler._send_json(404, [])
            return True
        handler._send_json(200, mlflow_reader.read_metric_history(run_dir, metric))
        return True
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
        print("画像学習パネル を起動しました")
        print(f"  mlruns: {mlflow_reader.DEFAULT_MLRUNS_DIR}")
        print(f"  ローカル: http://localhost:{PORT}")
        print("  Ctrl+C で終了")
        print("=" * 60)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n終了しました")


if __name__ == "__main__":
    main()
