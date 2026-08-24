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
import html
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
    dict(key="_car_diagram", category="collect", kind="diagram", label="センサー配置図",
         help="色つき=選択中のセンサー。オレンジの輪=上で選んだ走行モード(PLAN)が使うセンサー。"),
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
# 走行モード(PLAN)の解説データ
# PLAN_LIST は40種類以上あるが、処理内容ベースでいくつかの「系統」にまとめ、
# 個別に説明が必要なもの(ルールベース・ナビゲーション系)だけ単独エントリにする。
# 画像認識系(donkeycar/resnet18/mobilevit_*等)は処理の流れが共通なので1系統にまとめる。
# ---------------------------------------------------------------------------
_PLAN_SINGLE = {
    "manual": dict(category="手動", input="コントローラー", summary="人がジョイスティック/プロポ/キーボードで直接操作する。学習用データを集めるときの基本モード。",
                   files=["joystick.py", "pwm_controller.py"], highlight=[]),
    "go_straight": dict(category="ルールベース", input="なし", summary="判断ロジックを持たず、常にまっすぐ走るだけ。モーターやセンサーの動作確認用。",
                         files=["planner.py"], highlight=[]),
    "right_left_3": dict(category="ルールベース", input="超音波/LiDAR(左前・正面・右前)", summary="正面に障害物が近づいたら、左右どちらのセンサーがより開けているかを比べ、開けている側へ曲がる。",
                          files=["planner.py: Planner.right_left_3()"], highlight=["ultrasonic"]),
    "right_left_3_records": dict(category="ルールベース", input="超音波/LiDAR + 過去の操作履歴", summary="right_left_3と同じ判断に加え、直近の操作を記録・参照して同じ方向に曲がり続けないよう調整する版。",
                                  files=["planner.py: Planner.right_left_3_records()"], highlight=["ultrasonic"]),
    "wall_follow": dict(category="ルールベース", input="超音波/LiDAR(側面)", summary="片側の壁との距離が目標値(TARGET_RANGE)に近づくよう、単純な比例制御でステアリングを調整しながら壁沿いを走る。",
                         files=["planner.py: Planner.wall_follow()"], highlight=["ultrasonic"]),
    "wall_follow_pid": dict(category="ルールベース(PID)", input="超音波/LiDAR(側面)", summary="wall_followと同じ目的だが、PID制御(比例・積分・微分)を使うことで、より滑らかで安定した壁沿い走行になる。",
                             files=["planner.py: Planner.wall_follow_pid()"], highlight=["ultrasonic"]),
    "follow_the_gap": dict(category="ルールベース(反応型)", input="LiDAR(全点群)", summary="LiDARの点群から、障害物を避けた上で「一番広く開いている角度」を毎フレーム計算し、その方向へ走る回避アルゴリズム。",
                            files=["follow_the_gap.py"], highlight=["lidar"]),
    "rl": dict(category="強化学習", input="LiDAR(109次元の観測ベクトル)", summary="togikaidrive-sim(シミュレーター)上で強化学習(SAC/PPO/TD3等)を使って事前に学習させたポリシーで走行する。",
               files=["togikaidrive-sim/enjoy_rl.py", "togikaidrive-sim/run_f1tenth.py"], highlight=["lidar"]),
    "path_nav": dict(category="自己位置+経路追従", input="自己位置推定(SLAM/VSLAM/ArUco) + 記録済み経路", summary="自分の位置と向きを推定しながら、あらかじめ記録した経路(centerline/raceline)をpure pursuit法で追従する。",
                      files=["localization/path_follow.py"], highlight=["lidar"]),
    "waypoint_nav": dict(category="自己位置+目標点ナビ", input="自己位置推定 + 目標点リスト", summary="指定した座標(目標点)へ順番に向かって走る。到達時の挙動(停止/ループ/折り返し)も設定できる。",
                          files=["localization/waypoint_nav.py"], highlight=["lidar"]),
    "mpc": dict(category="自己位置+最適制御", input="自己位置推定 + 記録済み経路", summary="非線形モデル予測制御(iLQR)を使い、数手先の動きまで計算しながら経路に追従する、path_navの上位互換。",
                files=["localization/mpc_follow.py"], highlight=["lidar"]),
    "mppi": dict(category="自己位置+最適制御", input="自己位置推定 + 記録済み経路 + LiDAR", summary="サンプリングベースの最適制御(MPPI)で経路に追従しつつ、LiDARで検知した障害物も避けるようコストに織り込む。",
                 files=["localization/mppi_follow.py", "localization/mppi_core.py"], highlight=["lidar"]),
    "mppi_local": dict(category="ローカル最適制御", input="LiDAR(全点群のみ)", summary="地図や自己位置を使わず、その場のLiDAR点群だけを見て、開いた空間へ向かうMPPI制御を行う(follow_the_gapの発展版)。",
                        files=["localization/mppi_local.py"], highlight=["lidar"]),
    "ai_model": dict(category="AI(自動判別・推奨)", input="学習済みモデルによる", summary="学習済みモデルファイルの中身を読み取り、CNN画像モデル/系列モデル/超音波NNなどを自動で判別して使う。新規に学習する場合はこれを推奨。",
                      files=["model_inference.py", "run.py: _detect_ai_model_kind()"], highlight=[]),
    "nn": dict(category="AI(センサー値)", input="超音波センサーの値", summary="超音波センサーの値を入力にしたシンプルなニューラルネットワークで、ステアリング/スロットルを推論する(旧式。新規はai_model推奨)。",
               files=["train_pytorch.py"], highlight=["ultrasonic"]),
}

_IMAGE_FAMILY = dict(
    category="AI(画像CNN/Transformer)", input="カメラ画像",
    summary="カメラ画像を入力に、AIモデルでステアリング/スロットルを推論する。処理の流れ(画像→AI推論→操作値)はどれも共通で、違いはニューラルネットの構造(精度と速度のトレードオフ)。donkeycarが標準的な軽量モデル、resnet18/34やswin系はより高精度、mobilevit/mobilenet/efficientnet/edgenext/ghostnet系は軽量・高速志向。",
    files=["train_pytorch.py", "annotation_training_d2j (モデル定義)"], highlight=["camera_0"],
)
_IMAGE_PLANS = [
    "donkeycar", "donkey_fcn", "resnet18", "resnet34",
    "mobilevit_xxs", "mobilevit_xs", "mobilevit_s", "mobilevitv2_050",
    "mobilenetv3_small_100", "mobilenetv3_large_100", "mobilenetv4_conv_small",
    "efficientnet_lite0", "efficientnet_b0", "efficientnetv2_s",
    "convnext_nano", "convnext_tiny", "edgenext_xx_small", "edgenext_x_small",
    "mobileone_s0", "ghostnet_050", "shufflenetv2_x0_5",
    "swin_tiny_patch4_window7_224", "swin_tiny", "swin_s3_tiny_224",
    "swinv2_cr_tiny_ns_224", "swin_moe_tiny_patch4_window7_224", "efficientformer_l1",
]

_YOLO_FAMILY = dict(
    category="AI(物体検知ベース)", input="カメラ画像(YOLOで物体検知)",
    summary="YOLOで検知した物体(標識・障害物など)の種類や位置に応じて、あらかじめ決めたルールで減速・回避・モデル切り替えを行う。n/s/m/l/xはモデルサイズの違い(小さいほど高速、大きいほど高精度)。",
    files=["yolo_detection.py"], highlight=["camera_0"],
)
_YOLO_PLANS = ["yolo11n", "yolo11s", "yolo11m", "yolo11l", "yolo11x"]

_SEQUENCE_FAMILY = dict(
    category="AI(時系列モデル)", input="直近数フレーム分のセンサー値/画像特徴の推移",
    summary="1枚の画像・1回のセンサー値だけでなく、直近数フレームの「流れ」を考慮して推論するモデル。急なコーナーの手前の動きなど、時間的な文脈が重要な場面に強い。",
    files=["train_pytorch.py: load_sequence_model()"], highlight=["camera_0"],
)
_SEQUENCE_PLANS = ["gru", "tcn", "causal_cnn"]


def build_plan_info() -> dict:
    info = dict(_PLAN_SINGLE)
    for p in _IMAGE_PLANS:
        info[p] = _IMAGE_FAMILY
    for p in _YOLO_PLANS:
        info[p] = _YOLO_FAMILY
    for p in _SEQUENCE_PLANS:
        info[p] = _SEQUENCE_FAMILY
    return info


PLAN_INFO = build_plan_info()
_PLAN_INFO_FALLBACK = dict(category="詳細未整理", input="-", summary="このモードの解説はまだ用意されていません。planner.py の該当メソッドを確認してください。", files=[])

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


def read_line_meta(text: str) -> dict:
    """各フィールドが config.py の何行目の、どの行にあるかを読み取る(コード表示用)。"""
    meta = {}
    for f in FIELDS:
        key = f["key"]
        pat = _line_pattern(key)
        m = pat.search(text)
        if not m:
            meta[key] = None
            continue
        line_no = text.count("\n", 0, m.start()) + 1
        meta[key] = dict(
            line=line_no,
            prefix=m.group(1),
            comment=(m.group(3) or "").strip(),
            full=m.group(0),
        )
    return meta


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


def _html_escape(text: str) -> str:
    return html.escape(str(text), quote=True)


def render_field(field: dict, value, plan_groups, meta: dict) -> str:
    key = field["key"]
    label = field["label"]
    help_text = field["help"]
    kind = field["kind"]

    if kind == "diagram":
        return f'''
    <div class="field">
      <label class="field-label">{label}</label>
      <p class="field-help">{help_text}</p>
      <div class="car-diagram-wrap">
        <svg id="car-svg" viewBox="0 0 220 360"></svg>
      </div>
    </div>'''

    if kind == "select":
        options_html = ""
        for group in plan_groups:
            opts = "".join(
                f'<option value="{o["value"]}" title="{o["tip"]}" {"selected" if o["value"] == value else ""}>{o["value"]}</option>'
                for o in group["options"]
            )
            options_html += f'<optgroup label="{group["group"]}">{opts}</optgroup>'
        control = (f'<select name="{key}" data-kind="select" onchange="onPlanChange(this.value)">{options_html}</select>'
                   f'<div id="plan-info" class="plan-info"></div>')
    elif kind == "sensors":
        current = set(value or [])
        boxes = "".join(
            f'''<label class="chk"><input type="checkbox" name="{key}" value="{v}" {"checked" if v in current else ""}
                onchange="refreshCodePreview('{key}'); updateCarDiagram();">
                <span>{label_ja}</span></label>'''
            for v, label_ja in SENSOR_OPTIONS
        )
        control = f'<div class="chk-group" data-kind="sensors" data-key="{key}">{boxes}</div>'
    elif kind in ("int", "float"):
        step = field.get("step", 1 if kind == "int" else 0.01)
        minv = field.get("min", "")
        maxv = field.get("max", "")
        control = (f'<input type="number" name="{key}" value="{value}" step="{step}" '
                   f'min="{minv}" max="{maxv}" data-kind="{kind}" oninput="refreshCodePreview(\'{key}\')">')
    else:
        control = (f'<input type="text" name="{key}" value="{value if value is not None else ""}" '
                   f'data-kind="{kind}" oninput="refreshCodePreview(\'{key}\')">')

    code_html = ""
    m = meta.get(key)
    if m:
        code_html = f'''
      <div class="field-code" id="code-{key}" data-line="{m['line']}" data-prefix="{_html_escape(m['prefix'])}"
           data-comment="{_html_escape(m['comment'])}">
        <span class="code-loc">config.py {m['line']}行目</span>
        <code class="code-cur">{_html_escape(m['full'])}</code>
      </div>'''

    return f'''
    <div class="field">
      <label class="field-label">{label}</label>
      <p class="field-help">{help_text}</p>
      {control}
      <p class="field-error" data-error-for="{key}"></p>
      {code_html}
    </div>'''


def render_page() -> str:
    text = CONFIG_PATH.read_text(encoding="utf-8")
    values = read_values(text)
    plan_groups = read_plan_list(text)
    line_meta = read_line_meta(text)

    cards = ""
    for cat in CATEGORIES:
        accent = ACCENT_COLOR[cat["accent"]]
        tint = ACCENT_TINT[cat["accent"]]
        fields_html = "".join(
            render_field(f, values.get(f["key"]), plan_groups, line_meta)
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

    field_meta_js = {
        f["key"]: dict(kind=f["kind"], **line_meta[f["key"]])
        for f in FIELDS if f["kind"] != "diagram" and line_meta.get(f["key"])
    }

    plan_info_json = json.dumps(PLAN_INFO, ensure_ascii=False)
    plan_fallback_json = json.dumps(_PLAN_INFO_FALLBACK, ensure_ascii=False)
    return (
        HTML_SHELL
        .replace("__CARDS__", cards)
        .replace("__CONFIG_PATH__", str(CONFIG_PATH))
        .replace("__PLAN_INFO__", plan_info_json)
        .replace("__PLAN_FALLBACK__", plan_fallback_json)
        .replace("__PLAN_CURRENT__", json.dumps(values.get("PLAN")))
        .replace("__FIELD_META__", json.dumps(field_meta_js, ensure_ascii=False))
    )


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
  .plan-info {{
    margin-top: 0.7rem; background: var(--card-bg); border-radius: 10px; padding: 0.8rem 0.9rem;
    font-size: 0.83rem; line-height: 1.5;
  }}
  .plan-info .badges {{ display: flex; flex-wrap: wrap; gap: 0.4rem; margin-bottom: 0.5rem; }}
  .plan-info .badge {{
    display: inline-block; padding: 0.2rem 0.55rem; border-radius: 999px; font-size: 0.72rem;
    font-weight: 700;
  }}
  .plan-info .badge.category {{ background: var(--orange); color: #fff; }}
  .plan-info .badge.input {{ background: var(--steel); color: #fff; }}
  .plan-info .summary {{ color: var(--text-dark); margin: 0 0 0.4rem; }}
  .plan-info .files {{ margin: 0; color: var(--muted); font-size: 0.76rem; }}
  .plan-info .files code {{
    background: #fff; border: 1px solid #E4E7F0; border-radius: 5px; padding: 0.05rem 0.35rem;
    font-size: 0.72rem;
  }}

  /* コードプレビュー */
  .field-code {{
    margin-top: 0.5rem; background: var(--navy); border-radius: 8px; padding: 0.5rem 0.7rem;
    font-family: "SF Mono", "Menlo", "Consolas", monospace;
  }}
  .field-code .code-loc {{
    display: block; color: var(--steel-soft); font-size: 0.68rem; margin-bottom: 0.2rem;
    font-family: -apple-system, sans-serif; letter-spacing: 0.03em;
  }}
  .field-code code {{ display: block; font-size: 0.78rem; white-space: pre-wrap; word-break: break-all; }}
  .field-code .code-old {{ color: #6B7280; text-decoration: line-through; opacity: 0.8; }}
  .field-code .code-cur {{ color: #C7CEDE; }}
  .field-code .code-new {{ color: var(--orange); font-weight: 700; }}
  .field-code.changed {{ outline: 1px solid var(--orange); }}

  /* センサー配置図 */
  .car-diagram-wrap {{ display: flex; justify-content: center; padding: 0.4rem 0 0.2rem; }}
  #car-svg {{ width: 100%; max-width: 220px; height: auto; }}
  .car-body {{ fill: #EEF0F5; stroke: #D8DCE6; stroke-width: 2; }}
  .car-wheel {{ fill: #C7CCDA; }}
  .sensor-dot {{ fill: #C7CCDA; stroke: #fff; stroke-width: 1.5; transition: fill 0.2s ease; }}
  .sensor-dot.big {{ }}
  .sensor-dot.active {{ fill: var(--cyan); }}
  .sensor-ring {{ fill: none; stroke: transparent; stroke-width: 2.5; stroke-dasharray: 3 2; transition: stroke 0.2s ease; }}
  .sensor-ring.relevant {{ stroke: var(--orange); }}
  .sensor-ring.relevant.active-ring {{ stroke-dasharray: none; }}
  .sensor-label {{ font-size: 8px; fill: #9AA3B5; font-family: -apple-system, sans-serif; }}
  .sensor-label.active {{ fill: var(--text-dark); font-weight: 700; }}
  .lidar-sweep {{ fill: none; stroke: #D8DCE6; stroke-width: 1; stroke-dasharray: 2 3; }}
  .lidar-sweep.active {{ stroke: var(--cyan); }}

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
const PLAN_INFO = __PLAN_INFO__;
const PLAN_FALLBACK = __PLAN_FALLBACK__;

function updatePlanInfo(planValue) {{
  const panel = document.getElementById('plan-info');
  if (!panel) return;
  const info = PLAN_INFO[planValue] || PLAN_FALLBACK;
  const filesHtml = (info.files && info.files.length)
    ? '関連プログラム: ' + info.files.map(f => `<code>${{f}}</code>`).join(' ')
    : '';
  panel.innerHTML = `
    <div class="badges">
      <span class="badge category">${{info.category}}</span>
      <span class="badge input">入力: ${{info.input}}</span>
    </div>
    <p class="summary">${{info.summary}}</p>
    <p class="files">${{filesHtml}}</p>
  `;
}}

const FIELD_META = __FIELD_META__;
let CURRENT_PLAN = __PLAN_CURRENT__;

function onPlanChange(planValue) {{
  CURRENT_PLAN = planValue;
  updatePlanInfo(planValue);
  refreshCodePreview('PLAN');
  updateCarDiagram();
}}

document.addEventListener('DOMContentLoaded', () => {{
  updatePlanInfo(CURRENT_PLAN);
  renderCarDiagram();
  updateCarDiagram();
}});

// ---------------------------------------------------------------------
// コードプレビュー: フォームの値が config.py の実際の行にどう反映されるか
// ---------------------------------------------------------------------
function formatLiteral(kind, value) {{
  if (kind === 'str' || kind === 'select') return JSON.stringify(String(value));
  if (kind === 'int') {{
    const n = parseInt(value, 10);
    return String(Number.isFinite(n) ? n : value);
  }}
  if (kind === 'float') {{
    const n = parseFloat(value);
    return String(Number.isFinite(n) ? n : value);
  }}
  if (kind === 'sensors') {{
    return '[' + value.map(v => JSON.stringify(v)).join(', ') + ']';
  }}
  return JSON.stringify(String(value));
}}

function getCurrentValue(key) {{
  const kind = FIELD_META[key] ? FIELD_META[key].kind : null;
  if (kind === 'sensors') {{
    const group = document.querySelector(`.chk-group[data-key="${{key}}"]`);
    return Array.from(group.querySelectorAll('input[type=checkbox]:checked')).map(c => c.value);
  }}
  const el = document.querySelector(`[name="${{key}}"]`);
  return el ? el.value : null;
}}

function refreshCodePreview(key) {{
  const box = document.getElementById('code-' + key);
  const meta = FIELD_META[key];
  if (!box || !meta) return;

  const value = getCurrentValue(key);
  let newLiteral;
  try {{
    newLiteral = formatLiteral(meta.kind, value);
  }} catch (e) {{
    return;
  }}
  const comment = meta.comment ? '  ' + meta.comment : '';
  const newLine = meta.prefix + newLiteral + comment;

  if (newLine === meta.full) {{
    box.classList.remove('changed');
    box.innerHTML = `<span class="code-loc">config.py ${{meta.line}}行目</span><code class="code-cur">${{escapeHtml(meta.full)}}</code>`;
  }} else {{
    box.classList.add('changed');
    box.innerHTML = `<span class="code-loc">config.py ${{meta.line}}行目 (変更あり)</span>` +
      `<code class="code-old">${{escapeHtml(meta.full)}}</code>` +
      `<code class="code-new">${{escapeHtml(newLine)}}</code>`;
  }}
}}

function escapeHtml(s) {{
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}}

// ---------------------------------------------------------------------
// センサー配置図(上から見た車体)
// ---------------------------------------------------------------------
const SENSOR_POINTS = [
  {{key: 'ultrasonic', cx: 75, cy: 58, label: 'FrLH'}},
  {{key: 'ultrasonic', cx: 110, cy: 46, label: 'FrFR'}},
  {{key: 'ultrasonic', cx: 145, cy: 58, label: 'FrRH'}},
  {{key: 'ultrasonic', cx: 75, cy: 302, label: 'RrLH'}},
  {{key: 'ultrasonic', cx: 145, cy: 302, label: 'RrRH'}},
  {{key: 'camera_0', cx: 95, cy: 90, label: 'cam0'}},
  {{key: 'camera_1', cx: 125, cy: 90, label: 'cam1'}},
  {{key: 'gs2', cx: 110, cy: 114, label: 'GS2'}},
  {{key: 'lidar', cx: 110, cy: 178, label: 'LiDAR', big: true}},
  {{key: 'imu', cx: 75, cy: 200, label: 'IMU'}},
  {{key: 'optical_flow', cx: 145, cy: 200, label: 'OF'}},
  {{key: 'rpm', cx: 110, cy: 322, label: 'RPM'}},
];

function renderCarDiagram() {{
  const svg = document.getElementById('car-svg');
  if (!svg) return;
  const ns = 'http://www.w3.org/2000/svg';
  const el = (tag, attrs) => {{
    const n = document.createElementNS(ns, tag);
    for (const k in attrs) n.setAttribute(k, attrs[k]);
    return n;
  }};

  svg.appendChild(el('rect', {{x: 50, y: 20, width: 120, height: 320, rx: 28, class: 'car-body'}}));
  // ホイール
  [[42, 62], [164, 62], [42, 282], [164, 282]].forEach(([x, y]) => {{
    svg.appendChild(el('rect', {{x, y, width: 14, height: 34, rx: 4, class: 'car-wheel'}}));
  }});
  // 進行方向の矢印(前方)
  svg.appendChild(el('polygon', {{points: '110,26 100,40 120,40', fill: '#B9C0D4'}}));

  SENSOR_POINTS.forEach(p => {{
    const r = p.big ? 12 : 7;
    if (p.big) {{
      svg.appendChild(el('circle', {{cx: p.cx, cy: p.cy, r: 22, class: 'lidar-sweep', id: 'sweep-' + p.key}}));
    }}
    svg.appendChild(el('circle', {{
      cx: p.cx, cy: p.cy, r: r + 5, class: 'sensor-ring', id: 'ring-' + p.key + '-' + p.label,
      'data-key': p.key,
    }}));
    svg.appendChild(el('circle', {{
      cx: p.cx, cy: p.cy, r, class: 'sensor-dot' + (p.big ? ' big' : ''),
      id: 'dot-' + p.key + '-' + p.label, 'data-key': p.key,
    }}));
    const t = el('text', {{
      x: p.cx, y: p.cy + r + 11, class: 'sensor-label', 'text-anchor': 'middle',
      id: 'label-' + p.key + '-' + p.label, 'data-key': p.key,
    }});
    t.textContent = p.label;
    svg.appendChild(t);
  }});
}}

function updateCarDiagram() {{
  const svg = document.getElementById('car-svg');
  if (!svg) return;
  const activeSensors = new Set(getCurrentValue('ACTIVE_SENSORS') || []);
  const info = PLAN_INFO[CURRENT_PLAN] || PLAN_FALLBACK;
  const relevant = new Set(info.highlight || []);

  svg.querySelectorAll('[data-key]').forEach(elm => {{
    const key = elm.dataset.key;
    const isActive = activeSensors.has(key);
    const isRelevant = relevant.has(key);
    elm.classList.toggle('active', isActive);
    elm.classList.toggle('relevant', isRelevant);
    elm.classList.toggle('active-ring', isActive && isRelevant);
  }});
  svg.querySelectorAll('.lidar-sweep').forEach(elm => {{
    elm.classList.toggle('active', activeSensors.has('lidar'));
  }});
}}

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
