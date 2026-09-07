#!/usr/bin/env python3
"""
togikaidrive 設定エディタ
==========================
config.py(480項目・1281行の生Pythonファイル)を、ミニカーの処理カテゴリ別の
パネルUIから安全に編集できるようにするローカルツール。

- 標準ライブラリのみで動作(pip install不要。Raspberry Pi / Jetson でもそのまま動く)
- config.py の該当行だけを書き換える(ファイル全体を作り直さない)
- 保存前に必ずバックアップ(config.py.bak.<日時>)を作成する
- 「よく使う設定」はカード形式+説明文、それ以外の全項目は「詳細設定」として
  config.py自身のセクション見出しからその場で自動生成する(ハードコードしない)
- どちらの階層でも、保存前に「config.pyの何行目がどう変わるか」を
  差分プレビュー(変更前→変更後)で確認できる

使い方:
    python3 server.py
    → ブラウザで http://localhost:8899 を開く
    → 同じネットワーク内の他のPCからは http://<このPCのIPアドレス>:8899
"""
from __future__ import annotations

import ast
import hashlib
import html
import json
import re
import shutil
import socket
import sys
import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8899
# togikaidrive-config-editor/ と togikaidrive-dev/ は ト技会-minicar/ 直下の兄弟フォルダ
CONFIG_PATH = Path(__file__).resolve().parent.parent / "togikaidrive-dev" / "config.py"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# ---------------------------------------------------------------------------
# ミニカー処理カテゴリ(6分類)
# config.py 自身が持つ33個のセクション見出しを実際に集計し、この6分類に
# 自然にまとまることを確認済み(SECTION_CATEGORY で対応づけ)。
# ---------------------------------------------------------------------------
CATEGORIES = [
    dict(id="basic", title="基本設定", subtitle="デバイス・モニター・記録形式など", icon="🔧", accent="steel"),
    dict(id="perception", title="認知", subtitle="超音波・カメラ・LiDAR・IMU等のセンサー設定", icon="📡", accent="cyan"),
    dict(id="localization", title="自己位置推定", subtitle="SLAM / VSLAM / ArUco / AMCL（高度・任意）", icon="🧭", accent="cyan"),
    dict(id="decision", title="判断", subtitle="走行モード(PLAN)・AIモデル・走行ロジック", icon="🧠", accent="orange"),
    dict(id="control", title="操作", subtitle="モーター校正・コントローラー設定", icon="⚙️", accent="steel"),
    dict(id="fx", title="演出", subtitle="エンジン音など見た目・体験の演出", icon="🔊", accent="orange"),
]
CATEGORY_IDS = {c["id"] for c in CATEGORIES}

# ---------------------------------------------------------------------------
# よく使う設定(キュレーション。手作業で選定し、説明文をつけた項目)
# ---------------------------------------------------------------------------
CURATED_FIELDS = [
    # ============================== 基本設定 ==============================
    dict(key="MONITOR", category="basic", kind="bool", label="Webモニターを使う (MONITOR)",
         help="走行中の状態をブラウザ(http://<IP>:8000等)でリアルタイム確認できるようにする。"),
    dict(key="TERMINAL_PRINT", category="basic", kind="bool", label="ターミナル出力 (TERMINAL_PRINT)",
         help="走行中の状態をターミナルにも表示するか。"),
    dict(key="SAVE_FORMAT", category="basic", kind="choice", options=["csv", "ndjson", "donkeycar"],
         label="記録形式 (SAVE_FORMAT)", help="走行データの保存形式。data_viewer等で使うなら donkeycar。"),
    dict(key="AUTO_ZIP_ON_EXIT", category="basic", kind="bool", label="終了時に自動zip (AUTO_ZIP_ON_EXIT)",
         help="run.py終了時に記録フォルダを自動的にzip圧縮するか。"),

    # ============================== 認知 ==============================
    dict(key="ACTIVE_SENSORS", category="perception", kind="sensors", label="使用センサー (ACTIVE_SENSORS)",
         help="実際に使うセンサーを選ぶ。カメラ画像で学習するなら camera_0 を含める。"),
    dict(key="_car_diagram", category="perception", kind="diagram", label="センサー配置図",
         help="色つき=選択中のセンサー。オレンジの輪=「判断」カテゴリで選んだ走行モード(PLAN)が使うセンサー。"),
    dict(key="STOP_RANGE", category="perception", kind="int", min=0, max=2000, label="停止判定距離 (STOP_RANGE, mm)",
         help="この距離より障害物が近づいたら停止・後退の判断に使う。"),
    dict(key="DETECTION_RANGE", category="perception", kind="int", min=0, max=4000, label="検知開始距離 (DETECTION_RANGE, mm)",
         help="この距離から障害物として検知を始める。"),
    dict(key="IMAGE_W", category="perception", kind="int", min=32, max=1920, label="カメラ画像の幅 (IMAGE_W)",
         help="カメラ画像の横ピクセル数。学習モデルの入力サイズに合わせる(通常224)。"),
    dict(key="IMAGE_H", category="perception", kind="int", min=32, max=1080, label="カメラ画像の高さ (IMAGE_H)",
         help="カメラ画像の縦ピクセル数。"),
    dict(key="LIDAR_TYPE", category="perception", kind="choice", options=["AUTO", "TMINI", "UST20", "NONE"],
         label="LiDAR機種 (LIDAR_TYPE)", help="AUTOなら起動時に自動検出する。"),

    # ============================== 自己位置推定 ==============================
    dict(key="LIDAR_SLAM_BACKEND", category="localization", kind="choice",
         options=["none", "lidar_slam", "slam_toolbox", "amcl"],
         label="SLAMバックエンド (LIDAR_SLAM_BACKEND)",
         help="LiDARベースの自己位置推定方式。none=使わない。詳細は詳細設定またはスライド資料を参照。"),
    dict(key="LOCALIZATION_SOURCE", category="localization", kind="choice",
         options=["lidar_slam", "vslam", "aruco"],
         label="経路追従用の自己位置ソース (LOCALIZATION_SOURCE)",
         help="path_nav/waypoint_nav/mpc/mppi等が使う自己位置推定の情報源。"),

    # ============================== 判断 ==============================
    dict(key="PLAN", category="decision", kind="select", label="走行モード (PLAN)",
         help="判断ロジックの種類。手動でデータ収集するなら manual、学習済みAIで走らせるなら ai_model。"),
    dict(key="HAND_SIDE", category="decision", kind="choice", options=["right", "left"],
         label="壁沿い走行の基準側 (HAND_SIDE)", help="wall_follow系モードで、右手法/左手法どちらを使うか。"),
    dict(key="TARGET_RANGE", category="decision", kind="int", min=0, max=2000, label="壁との目標距離 (TARGET_RANGE, mm)",
         help="wall_follow系モードで維持しようとする壁との距離。"),
    dict(key="K_P", category="decision", kind="float", min=0, max=10, step=0.001, label="PID比例ゲイン (K_P)",
         help="壁沿い走行PID制御の比例項。大きいほど反応が敏感になる。"),
    dict(key="K_I", category="decision", kind="float", min=0, max=10, step=0.0001, label="PID積分ゲイン (K_I)",
         help="定常的なズレを補正する積分項。"),
    dict(key="K_D", category="decision", kind="float", min=0, max=10, step=0.0001, label="PID微分ゲイン (K_D)",
         help="急な変化を抑える微分項。振動を抑えたい時に上げる。"),
    dict(key="FTG_SAFETY_DISTANCE", category="decision", kind="int", min=0, max=3000,
         label="Follow the Gap 安全距離 (FTG_SAFETY_DISTANCE, mm)",
         help="follow_the_gap/mppi_localモードで障害物とみなす安全マージン。"),
    dict(key="EPOCHS", category="decision", kind="int", min=1, max=500, label="学習回数 (EPOCHS)",
         help="train_pytorch.py実行時、集めたデータを何周学習させるか。まずは30前後が目安。"),
    dict(key="BATCH_SIZE", category="decision", kind="int", min=1, max=512, label="バッチサイズ (BATCH_SIZE)",
         help="1回の学習ステップで同時に見せるデータ数。"),
    dict(key="HIDDEN_DIM", category="decision", kind="int", min=1, max=1024, label="隠れ層の大きさ (HIDDEN_DIM)",
         help="ニューラルネットの1層あたりのノード数。"),
    dict(key="NUM_HIDDEN_LAYERS", category="decision", kind="int", min=1, max=20, label="隠れ層の数 (NUM_HIDDEN_LAYERS)",
         help="ニューラルネットの層の深さ。基本は2〜3層で十分。"),
    dict(key="MODEL_DIR", category="decision", kind="str", label="モデル保存フォルダ (MODEL_DIR)",
         help="学習済みモデルを保存・読み込みするフォルダ名。通常は変更不要。"),
    dict(key="MODEL_NAME", category="decision", kind="str", label="使用するモデルファイル名 (MODEL_NAME)",
         help="自動走行時に読み込む学習済みモデルのファイル名。"),

    # ============================== 操作 ==============================
    dict(key="FORWARD_STRAIGHT", category="control", kind="float", min=-1, max=1, step=0.05,
         label="直線速度 (FORWARD_STRAIGHT)", help="まっすぐ進む速さ。0〜1の範囲が目安。"),
    dict(key="FORWARD_CORNER", category="control", kind="float", min=-1, max=1, step=0.05,
         label="カーブ速度 (FORWARD_CORNER)", help="カーブでの速さ。直線速度より少し小さめが目安。"),
    dict(key="STEERING_CENTER_PWM", category="control", kind="int", min=100, max=600,
         label="ステアリング中央PWM (STEERING_CENTER_PWM)", help="ステアリングがまっすぐになるPWM値。motor.pyで調整した値を入れる。"),
    dict(key="STEERING_WIDTH_PWM", category="control", kind="int", min=0, max=300,
         label="ステアリング振れ幅PWM (STEERING_WIDTH_PWM)", help="中央から左右にどれだけ振れるか。"),
    dict(key="THROTTLE_STOPPED_PWM", category="control", kind="int", min=100, max=600,
         label="スロットル停止PWM (THROTTLE_STOPPED_PWM)", help="モーターが止まるPWM値(ニュートラル)。"),
    dict(key="THROTTLE_FORWARD_PWM", category="control", kind="int", min=100, max=600,
         label="スロットル前進最大PWM (THROTTLE_FORWARD_PWM)", help="前進最大速度のPWM値。"),
    dict(key="THROTTLE_REVERSE_PWM", category="control", kind="int", min=100, max=600,
         label="スロットル後退最大PWM (THROTTLE_REVERSE_PWM)", help="後退最大速度のPWM値。"),
    dict(key="CONTROLLER_TYPE", category="control", kind="choice", options=["joystick", "pwm", "keyboard"],
         label="コントローラー種類 (CONTROLLER_TYPE)", help="手動操作に使う入力装置。"),
    dict(key="JOYSTICK_STEERING_SCALE", category="control", kind="float", min=-1, max=1, step=0.1,
         label="ジョイスティック ステアリング感度 (JOYSTICK_STEERING_SCALE)", help="左右が逆に動く場合は符号を反転する。"),
    dict(key="JOYSTICK_THROTTLE_SCALE", category="control", kind="float", min=-1, max=1, step=0.1,
         label="ジョイスティック スロットル感度 (JOYSTICK_THROTTLE_SCALE)", help="前後が逆に動く場合は符号を反転する。"),

    # ============================== 演出 ==============================
    dict(key="USE_ENGINE_SOUND", category="fx", kind="bool", label="エンジン音を再生 (USE_ENGINE_SOUND)",
         help="throttle値に応じてスピーカーからエンジン音を再生する(走行には影響しない演出機能)。"),
    dict(key="ENGINE_SOUND_VOLUME", category="fx", kind="float", min=0, max=1, step=0.05,
         label="エンジン音量 (ENGINE_SOUND_VOLUME)", help="マスター音量。0.0〜1.0。"),
]
CURATED_KEYS = {f["key"] for f in CURATED_FIELDS if not f["key"].startswith("_")}

# ---------------------------------------------------------------------------
# config.py の33セクション見出し → 6処理カテゴリ への対応づけ
# (実ファイルをgrepして集計したセクション一覧に基づく。config.py側の見出しが
#  変わらない限り有効。見つからない見出しは "basic" にフォールバックする)
# ---------------------------------------------------------------------------
SECTION_CATEGORY = {
    "デバイス設定": "basic",
    "出力・モニタリング設定": "basic",
    "VSLAM (Visual SLAM via Isaac ROS Visual SLAM + RealSense D435i)": "localization",
    "ナビゲーション（自己位置ベース）共通設定": "localization",
    "調停層（Arbiter）: 主制御(PLAN)に副制御を組み合わせる": "decision",
    "ArUco Localization (外部PCの俯瞰カメラ + 各車ルーフマーカーによる絶対自己位置)": "localization",
    "モーター制御基本設定": "control",
    "測距センサー検知範囲設定（超音波/LiDAR共通、単位: mm）": "perception",
    "走行プラン（判断モード）選択": "decision",
    "各種走行モード固有のパラメータ": "decision",
    "復帰モード設定": "control",
    "車両調整用パラメータ（ハードウェア設定）": "control",
    "機械学習モデル設定（NN/CNN）": "decision",
    "マルチカメラ・仮想ソース推論設定": "decision",
    "超音波センサ設定": "perception",
    "カメラ設定": "perception",
    "LiDAR設定": "perception",
    "ROS2 slam_toolbox 統合（lidar_slam の代替・configで選択）": "localization",
    "LiDAR機種別設定": "perception",
    "YDLidar GS2（近距離専用ライン測距センサー, 〜30cm / 160点）": "perception",
    "Follow the Gap 設定": "decision",
    "LiDAR自動スロットル調整機能": "decision",
    "コントローラー設定": "control",
    "IMU/ジャイロ設定": "perception",
    "RPMセンサー設定": "perception",
    "オプティカルフローセンサー設定": "perception",
    "Speed PID制御設定（速度フィードバック制御）": "decision",
    "走行記録設定": "basic",
    "シミュレーションモード": "basic",
    "位置推論とモデル切り替え設定": "decision",
    "YOLO物体検知設定": "decision",
    "エンジン音設定（engine_sound.py）": "fx",
    "強化学習（RL）プラン設定": "decision",
}

# config.py 側で PLAN_LIST など「別枠で特別扱いする」トップレベル変数名(詳細設定には出さない)
_EXCLUDE_FROM_ADVANCED = {"PLAN_LIST"}

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


# ---------------------------------------------------------------------------
# config.py の読み書き(キー単位で汎用に扱う)
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


def parse_config_sections(text: str) -> list[tuple[int, str]]:
    """config.py 自身の "# ====...====" 見出しブロックから (行番号, 見出し文) の一覧を抽出する。
    見出しは bar / title / bar の3行1組が基本だが、bar / title のみ(閉じbarなし)の
    崩れたパターンも許容する。"""
    lines = text.split("\n")
    n = len(lines)
    sections: list[tuple[int, str]] = []
    i = 0
    while i < n:
        if lines[i].startswith("# ====="):
            if i + 1 < n and lines[i + 1].startswith("#") and not lines[i + 1].startswith("# ====="):
                title = lines[i + 1].strip().lstrip("#").strip()
                sections.append((i + 1, title))
                j = i + 2
                if j < n and lines[j].startswith("# ====="):
                    j += 1
                i = j
                continue
        i += 1
    return sections


def read_key_values(keys: list[str], text: str) -> dict:
    values = {}
    for key in keys:
        m = _line_pattern(key).search(text)
        if not m:
            values[key] = None
            continue
        raw = m.group(2).strip()
        try:
            values[key] = ast.literal_eval(raw)
        except Exception:
            values[key] = raw.strip("\"'")
    return values


def read_line_meta(keys: list[str], text: str) -> dict:
    """指定キー群が config.py の何行目の、どの行にあるかを読み取る(コード表示用)。
    値が単純なPythonリテラルとして解釈できない場合(他の変数を参照する式・複数行の
    リスト/辞書など)は editable=False とし、表示専用にする。"""
    meta = {}
    for key in keys:
        m = _line_pattern(key).search(text)
        if not m:
            meta[key] = None
            continue
        line_no = text.count("\n", 0, m.start()) + 1
        raw = m.group(2)  # 触っていない項目を保存時に再現できるよう、空白を落とさずそのまま保持する
        try:
            ast.literal_eval(raw.strip())
            editable = True
        except Exception:
            editable = False
        meta[key] = dict(
            line=line_no,
            prefix=m.group(1),
            comment=(m.group(3) or "").strip(),
            # コメント前の空白(行ごとに揃っていないことがある)をそのまま保持する。
            # JS側の変更判定はこれを使って行を再構築するので、表示用に strip() した
            # comment とは別に持つ。
            comment_raw=m.group(3) or "",
            full=m.group(0),
            raw=raw,
            editable=editable,
        )
    return meta


def build_advanced_sections(text: str) -> dict:
    """カテゴリID -> [ {title, fields:[{key, meta}]} ] を、config.py自身のセクション
    構造から動的に組み立てる(キュレーション済みキーとPLAN_LISTは除外)。"""
    key_pat = re.compile(r"^([A-Z][A-Z0-9_]*)\s*=")
    lines = text.split("\n")
    sections = parse_config_sections(text)
    starts = [s for s, _ in sections] + [len(lines)]

    result = {c["id"]: [] for c in CATEGORIES}
    for idx, (start, title) in enumerate(sections):
        end = starts[idx + 1]
        keys = []
        for ln in lines[start:end]:
            m = key_pat.match(ln)
            if m:
                keys.append(m.group(1))
        keys = [k for k in keys if k not in CURATED_KEYS and k not in _EXCLUDE_FROM_ADVANCED]
        if not keys:
            continue
        cat_id = SECTION_CATEGORY.get(title, "basic")
        meta = read_line_meta(keys, text)
        fields = [dict(key=k, meta=meta[k]) for k in keys if meta.get(k)]
        if fields:
            result[cat_id].append(dict(title=title, fields=fields))
    return result


def build_code_log(text: str) -> dict:
    """カテゴリID -> [ {title, start_line, code} ] を、config.py自身のセクション区切りから
    そのまま切り出す(詳細設定のようなkey=value抽出ではなく、生コードそのもの)。"""
    lines = text.split("\n")
    sections = parse_config_sections(text)
    starts = [s for s, _ in sections]

    result = {c["id"]: [] for c in CATEGORIES}
    for idx, (title_idx, title) in enumerate(sections):
        bar_idx = title_idx - 1  # 見出しの開始bar行(0-indexed)
        next_bar_idx = (starts[idx + 1] - 1) if idx + 1 < len(sections) else len(lines)
        block = lines[bar_idx:next_bar_idx]
        while block and block[-1].strip() == "":
            block.pop()
        cat_id = SECTION_CATEGORY.get(title, "basic")
        result[cat_id].append(dict(title=title, start_line=bar_idx + 1, code="\n".join(block)))
    return result


def literal_for(kind: str, value, field: dict | None = None) -> str:
    if kind in ("str", "select", "choice"):
        return json.dumps(str(value))
    if kind == "int":
        return str(int(value))
    if kind == "float":
        return str(float(value))
    if kind == "bool":
        return "True" if value else "False"
    if kind == "sensors":
        items = [str(v) for v in value if str(v).strip()]
        return "[" + ", ".join(json.dumps(v) for v in items) + "]"
    if kind == "raw":
        # value は既にconfig.py上のPythonリテラル文字列そのもの(検証済み)
        return str(value)
    raise ValueError(f"unknown kind: {kind}")


def validate(kind: str, key: str, value, field: dict | None = None):
    if kind == "int":
        try:
            v = int(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} は整数で入力してください")
        if field and "min" in field and v < field["min"]:
            raise ValueError(f"{key} は {field['min']} 以上にしてください")
        if field and "max" in field and v > field["max"]:
            raise ValueError(f"{key} は {field['max']} 以下にしてください")
        return v
    if kind == "float":
        try:
            v = float(value)
        except (TypeError, ValueError):
            raise ValueError(f"{key} は数値で入力してください")
        if field and "min" in field and v < field["min"]:
            raise ValueError(f"{key} は {field['min']} 以上にしてください")
        if field and "max" in field and v > field["max"]:
            raise ValueError(f"{key} は {field['max']} 以下にしてください")
        return v
    if kind == "bool":
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("true", "1", "yes", "on")
    if kind in ("str", "select"):
        v = str(value).strip()
        if not v:
            raise ValueError(f"{key} を入力してください")
        return v
    if kind == "choice":
        v = str(value).strip()
        if not v:
            raise ValueError(f"{key} を入力してください")
        if field and field.get("options") and v not in field["options"]:
            raise ValueError(f"{key} は {field['options']} のいずれかにしてください")
        return v
    if kind == "sensors":
        if not isinstance(value, list) or not value:
            raise ValueError("センサーを最低1つ選んでください")
        return [str(v) for v in value]
    if kind == "raw":
        # 触っていない項目をそのまま送り返してきた場合に元の空白をstripで潰さないよう、
        # 検証のためのstripは別変数で行い、返す値は受け取ったままにする
        text = str(value)
        if text.strip() == "":
            raise ValueError(f"{key} を入力してください")
        try:
            ast.literal_eval(text.strip())
        except Exception as e:
            raise ValueError(f"{key} の書き方が正しくありません(Pythonの値として解釈できません): {e}")
        return text
    raise ValueError(f"unknown kind: {kind}")


def write_values(new_values: dict, kinds: dict, fields_by_key: dict) -> Path:
    """new_values: {key: 検証済みの値}, kinds: {key: kind}, fields_by_key: {key: fieldディクショナリ(min/max/options等)}

    保存フォームは(触っていない項目も含め)全項目を毎回送ってくるため、実際に内容が
    変わった行だけを書き換える(触っていない行はバイト単位で元のまま残す)。
    """
    text = CONFIG_PATH.read_text(encoding="utf-8")
    backup_path = _make_backup()

    for key, value in new_values.items():
        kind = kinds[key]
        literal = literal_for(kind, value, fields_by_key.get(key))
        pat = _line_pattern(key)

        def repl(m, literal=literal):
            comment = m.group(3) or ""
            new_line = f"{m.group(1)}{literal}{comment}"
            return new_line if new_line != m.group(0) else m.group(0)

        text, n = pat.subn(repl, text, count=1)
        if n == 0:
            raise ValueError(f"config.py 内に {key} の行が見つかりませんでした")

    CONFIG_PATH.write_text(text, encoding="utf-8")
    return backup_path


def _make_backup() -> Path:
    backup_path = CONFIG_PATH.with_name(
        f"config.py.bak.{datetime.datetime.now():%Y%m%d_%H%M%S}"
    )
    shutil.copy2(CONFIG_PATH, backup_path)
    return backup_path


# ---------------------------------------------------------------------------
# モーター初期化(実機があればMotor、無ければモック)
# 「操作」カテゴリのモーター校正ウィジェットで使う。motor.py自体は一切変更せず、
# 公開インターフェース(set_steering_pwm_value/set_throttle_pwm_value/pwm.set_pwm/
# CHANNEL_STEERING/CHANNEL_THROTTLE/cleanup)を外から使うだけ。Adafruit_PCA9685が
# 無い環境(開発機など)では自動的にモック(ログ出力のみ)にフォールバックし、UIと
# config.py書き込みのロジックだけは実機が無くても確認できるようにする。
# ---------------------------------------------------------------------------
TOGIKAIDRIVE_DEV_DIR = CONFIG_PATH.parent


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
MOTOR_IMPORT_ERROR = ""
motor_instance = None
MOTOR_RAW_PWM_RANGE = (100, 600)


def init_motor() -> None:
    global HARDWARE_AVAILABLE, MOTOR_IMPORT_ERROR, motor_instance
    try:
        sys.path.insert(0, str(TOGIKAIDRIVE_DEV_DIR))
        import motor as motor_module  # noqa: E402  (togikaidrive-dev/motor.py)
        motor_instance = motor_module.Motor()
        HARDWARE_AVAILABLE = True
        print("実機のMotorを初期化しました(PCA9685接続済み)")
    except Exception as e:  # noqa: BLE001  -- 開発機やライブラリ未導入時は握りつぶしてモックへ
        MOTOR_IMPORT_ERROR = f"{type(e).__name__}: {e}"
        motor_instance = MockMotor()
        HARDWARE_AVAILABLE = False
        print(f"実機のMotorを初期化できなかったため、モックモードで起動します({MOTOR_IMPORT_ERROR})")


# ---------------------------------------------------------------------------
# キャッシュ
# 起動時にconfig.pyを読み込んでパース結果一式をキャッシュし、以降はハッシュが
# 一致する限り再パースせずに使い回す。/save や テンプレート適用など、config.py
# を書き換える操作の直後は force=True で明示的に作り直す。
# ---------------------------------------------------------------------------
_CACHE: dict = {"hash": None, "snapshot": None}


def _compute_snapshot(text: str) -> dict:
    curated_keys = [f["key"] for f in CURATED_FIELDS if not f["key"].startswith("_")]
    values = read_key_values(curated_keys, text)
    plan_groups = read_plan_list(text)
    curated_meta = read_line_meta(curated_keys, text)
    advanced = build_advanced_sections(text)
    code_log = build_code_log(text)

    field_defs = {}
    for f in CURATED_FIELDS:
        if f["kind"] != "diagram":
            field_defs[f["key"]] = f
    for sections in advanced.values():
        for sec in sections:
            for fmeta in sec["fields"]:
                if fmeta["meta"]["editable"]:
                    field_defs[fmeta["key"]] = dict(key=fmeta["key"], kind="raw")

    return dict(
        text=text, values=values, plan_groups=plan_groups, curated_meta=curated_meta,
        advanced=advanced, code_log=code_log, field_defs=field_defs,
    )


def get_snapshot(force: bool = False) -> tuple[dict, bool]:
    """(snapshot, regenerated) を返す。regenerated は今回の呼び出しでキャッシュを
    作り直したかどうか(config.pyの内容が前回から変わっていたか)。"""
    text = CONFIG_PATH.read_text(encoding="utf-8")
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if not force and _CACHE["hash"] == h and _CACHE["snapshot"] is not None:
        return _CACHE["snapshot"], False
    snapshot = _compute_snapshot(text)
    _CACHE["hash"] = h
    _CACHE["snapshot"] = snapshot
    return snapshot, True


def invalidate_cache() -> None:
    _CACHE["hash"] = None
    _CACHE["snapshot"] = None


# ---------------------------------------------------------------------------
# テンプレート(現在のconfig.pyを任意名で保存・一覧・適用・削除)
# ---------------------------------------------------------------------------
def _safe_template_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ValueError("テンプレート名を入力してください")
    if not re.fullmatch(r"[\w\-]+", name):
        raise ValueError("テンプレート名に使えるのは英数字・日本語・_ - のみです(スペースや記号は不可)")
    return name


def list_templates() -> list:
    TEMPLATES_DIR.mkdir(exist_ok=True)
    items = []
    for p in sorted(TEMPLATES_DIR.glob("*.py")):
        stat = p.stat()
        items.append(dict(
            name=p.stem,
            saved_at=datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M"),
            size=stat.st_size,
        ))
    return items


def save_template(raw_name: str) -> str:
    name = _safe_template_name(raw_name)
    TEMPLATES_DIR.mkdir(exist_ok=True)
    shutil.copy2(CONFIG_PATH, TEMPLATES_DIR / f"{name}.py")
    return name


def apply_template(raw_name: str) -> Path:
    name = _safe_template_name(raw_name)
    src = TEMPLATES_DIR / f"{name}.py"
    if not src.exists():
        raise ValueError(f"テンプレート「{name}」が見つかりません")
    backup_path = _make_backup()
    shutil.copy2(src, CONFIG_PATH)
    invalidate_cache()
    return backup_path


def delete_template(raw_name: str) -> None:
    name = _safe_template_name(raw_name)
    p = TEMPLATES_DIR / f"{name}.py"
    if p.exists():
        p.unlink()


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
    elif kind == "choice":
        opts = "".join(
            f'<option value="{o}" {"selected" if o == value else ""}>{o}</option>'
            for o in field.get("options", [])
        )
        control = f'<select name="{key}" data-kind="choice" onchange="refreshCodePreview(\'{key}\')">{opts}</select>'
    elif kind == "bool":
        checked = "checked" if value else ""
        control = (f'<label class="chk single"><input type="checkbox" name="{key}" data-kind="bool" {checked} '
                   f'onchange="refreshCodePreview(\'{key}\')"><span>有効にする</span></label>')
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


def render_motor_calibration_widget() -> str:
    """「操作」カテゴリの先頭に差し込むモーター校正ウィジェット。
    ここで確定した値は既存の STEERING_CENTER_PWM 等の数値入力フィールドに直接
    反映され(motorSetField→refreshCodePreview)、以降は他のフィールドと全く同じ
    差分プレビュー・変更件数カウンター・「変更を保存」ボタンで扱われる
    (このウィジェット専用の保存経路は持たない)。"""
    status_html = (
        '<span class="hw-badge hw-on">🟢 実機接続中</span>'
        if HARDWARE_AVAILABLE else
        f'<span class="hw-badge hw-off" title="{_html_escape(MOTOR_IMPORT_ERROR)}">⚪ モック(シミュレーション)モード</span>'
    )
    return f'''
    <div class="motor-widget">
      <div class="motor-widget-head">
        <h3>🔧 モーター校正</h3>
        {status_html}
      </div>
      <p class="field-help">
        実際にサーボ・ESCを動かして校正できます。確定した値は下の数値フィールドに反映されますが、
        <b>ページ下部の「変更を保存」を押すまではconfig.pyには書き込まれません。</b>
      </p>
      <div class="warning">
        ⚠️ ジジっとノイズが鳴り続ける場合は壊れる兆候なので、すぐに値を戻してください。
        ページを開いただけでは何も送信されません(スライダーやボタンを操作した時だけ実機に送信します)。
      </div>

      <div class="slider-row">
        <label>ライブテスト・ステアリング <span id="motor-steering-val">0.00</span></label>
        <input type="range" id="motor-steering-slider" min="-1" max="1" step="0.05" value="0" oninput="motorSendLive()">
      </div>
      <div class="slider-row">
        <label>ライブテスト・スロットル <span id="motor-throttle-val">0.00</span></label>
        <input type="range" id="motor-throttle-slider" min="-1" max="1" step="0.05" value="0" oninput="motorSendLive()">
      </div>

      <div class="motor-calib-block">
        <h4>ステアリング校正</h4>
        <div class="raw-row">
          <input type="number" id="motor-steering-raw-input" placeholder="例: 430" min="100" max="600">
          <button type="button" onclick="motorTestRaw('steering')">送信(テスト)</button>
        </div>
        <div class="lock-buttons">
          <button type="button" onclick="motorLockSteeringCenter()">これを中央にする</button>
          <button type="button" onclick="motorLockSteeringExtreme()">これを左右どちらかの最大にする</button>
        </div>
      </div>

      <div class="motor-calib-block">
        <h4>スロットル校正</h4>
        <div class="raw-row">
          <input type="number" id="motor-throttle-raw-input" placeholder="例: 380" min="100" max="600">
          <button type="button" onclick="motorTestRaw('throttle')">送信(テスト)</button>
        </div>
        <div class="lock-buttons">
          <button type="button" onclick="motorLockThrottle('STOPPED')">これを停止(ニュートラル)にする</button>
          <button type="button" onclick="motorLockThrottle('FORWARD')">これを前進最大にする</button>
          <button type="button" onclick="motorLockThrottle('REVERSE')">これを後退最大にする</button>
        </div>
      </div>

      <button type="button" id="motor-stop-btn" onclick="motorStop()">■ 停止</button>
    </div>'''


def render_advanced_sections(sections: list[dict]) -> str:
    if not sections:
        return ""
    total = sum(len(s["fields"]) for s in sections)
    body = ""
    for sec in sections:
        rows = ""
        for f in sec["fields"]:
            key = f["key"]
            m = f["meta"]
            if m["editable"]:
                rows += f'''
              <tr>
                <td><code>{_html_escape(key)}</code></td>
                <td class="adv-value-cell">
                  <input type="text" class="adv-input" name="{key}" data-kind="raw"
                         value="{_html_escape(m['raw'])}" oninput="refreshCodePreview('{key}')">
                  <div class="field-code" id="code-{key}" data-line="{m['line']}"
                       data-prefix="{_html_escape(m['prefix'])}" data-comment="{_html_escape(m['comment'])}">
                    <span class="code-loc">config.py {m['line']}行目</span>
                    <code class="code-cur">{_html_escape(m['full'])}</code>
                  </div>
                  <p class="field-error" data-error-for="{key}"></p>
                </td>
              </tr>'''
            else:
                rows += f'''
              <tr class="readonly">
                <td><code>{_html_escape(key)}</code></td>
                <td class="adv-value-cell">
                  <code class="code-readonly">{_html_escape(m['full'])}</code>
                  <p class="field-help">他の設定を参照する計算式のため、この画面では編集できません(config.py {m['line']}行目を直接編集してください)。</p>
                </td>
              </tr>'''
        body += f'''
        <div class="adv-subsection">
          <h4>{_html_escape(sec["title"])}</h4>
          <table class="adv-table"><tbody>{rows}</tbody></table>
        </div>'''
    return f'''
    <details class="advanced">
      <summary>詳細設定を表示（{total}項目）</summary>
      {body}
    </details>'''


def render_code_log_panel(code_log: dict) -> str:
    body = ""
    for cat in CATEGORIES:
        secs = code_log.get(cat["id"], [])
        if not secs:
            continue
        total_lines = sum(len(s["code"].split("\n")) for s in secs)
        blocks = ""
        for s in secs:
            numbered = "\n".join(
                f"{s['start_line'] + i:>5} | {line}"
                for i, line in enumerate(s["code"].split("\n"))
            )
            blocks += f'''
            <div class="codelog-block">
              <div class="codelog-title">
                <span>{_html_escape(s["title"])}</span>
                <span class="codelog-loc">config.py {s["start_line"]}行目〜</span>
              </div>
              <pre class="codelog-pre">{_html_escape(numbered)}</pre>
            </div>'''
        body += f'''
        <details class="advanced codelog-category">
          <summary>{cat["icon"]} {cat["title"]}（約{total_lines}行）</summary>
          {blocks}
        </details>'''
    return body


def render_page() -> str:
    snap, _ = get_snapshot()
    values = snap["values"]
    plan_groups = snap["plan_groups"]
    curated_meta = snap["curated_meta"]
    advanced = snap["advanced"]
    code_log = snap["code_log"]

    tabs_nav = ""
    panels = ""
    for i, cat in enumerate(CATEGORIES):
        accent = ACCENT_COLOR[cat["accent"]]
        tint = ACCENT_TINT[cat["accent"]]
        active = "active" if i == 0 else ""
        tabs_nav += (f'<button class="tab-btn {active}" data-tab="{cat["id"]}" '
                     f'onclick="switchTab(\'{cat["id"]}\')">{cat["icon"]} {cat["title"]}</button>')

        fields_html = "".join(
            render_field(f, values.get(f["key"]), plan_groups, curated_meta)
            for f in CURATED_FIELDS if f["category"] == cat["id"]
        )
        if cat["id"] == "control":
            fields_html = render_motor_calibration_widget() + fields_html
        advanced_html = render_advanced_sections(advanced.get(cat["id"], []))

        panels += f'''
        <section class="tab-panel {active}" id="panel-{cat["id"]}">
          <div class="panel-head" style="background:{tint}">
            <h2>{cat["icon"]} {cat["title"]}</h2>
            <p>{cat["subtitle"]}</p>
          </div>
          <div class="card">
            <div class="card-body" style="border-color:{accent}22">{fields_html}</div>
          </div>
          {advanced_html}
        </section>'''

    # 7個目のタブ: config.pyの実コードをカテゴリ別に読み取り専用で表示
    tabs_nav += '<button class="tab-btn" data-tab="codelog" onclick="switchTab(\'codelog\')">📄 コード</button>'
    panels += f'''
    <section class="tab-panel" id="panel-codelog">
      <div class="panel-head" style="background:{PALETTE["steel_tint"]}">
        <h2>📄 コード</h2>
        <p>config.py の実際のコードを、カテゴリごとにそのまま表示します(読み取り専用)。</p>
      </div>
      {render_code_log_panel(code_log)}
    </section>'''

    field_meta_js = {key: dict(kind=f["kind"], **curated_meta[key])
                      for key, f in ((f["key"], f) for f in CURATED_FIELDS if f["kind"] != "diagram")
                      if curated_meta.get(key)}
    for sections in advanced.values():
        for sec in sections:
            for fmeta in sec["fields"]:
                if fmeta["meta"]["editable"]:
                    field_meta_js[fmeta["key"]] = dict(kind="raw", **fmeta["meta"])

    plan_info_json = json.dumps(PLAN_INFO, ensure_ascii=False)
    plan_fallback_json = json.dumps(_PLAN_INFO_FALLBACK, ensure_ascii=False)
    return (
        HTML_SHELL
        .replace("__TABS_NAV__", tabs_nav)
        .replace("__PANELS__", panels)
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
    --text-dark: {PALETTE["text_dark"]}; --muted: {PALETTE["muted"]}; --orange-tint: {PALETTE["orange_tint"]};
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: #F7F8FB; color: var(--text-dark);
    font-family: -apple-system, BlinkMacSystemFont, "Hiragino Sans", "Yu Gothic", "Segoe UI", sans-serif;
    padding-bottom: 6rem;
  }}
  header {{
    background: var(--navy); color: #fff; padding: 1.6rem 1.5rem 1.6rem;
  }}
  header .eyebrow {{ color: var(--cyan); font-size: 0.75rem; font-weight: 700; letter-spacing: 0.12em; }}
  header h1 {{ margin: 0.3rem 0 0.4rem; font-size: 1.5rem; }}
  header p {{ margin: 0; color: #B9C0D4; font-size: 0.85rem; }}
  .header-top {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }}
  .header-actions {{ display: flex; gap: 0.5rem; flex-shrink: 0; }}
  .ghost-btn {{
    background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.2); color: #fff;
    padding: 0.5rem 0.8rem; border-radius: 999px; font-size: 0.78rem; font-weight: 700; cursor: pointer;
    white-space: nowrap;
  }}
  .ghost-btn:hover {{ background: rgba(255,255,255,0.16); }}

  .templates-panel {{
    margin-top: 1.1rem; background: rgba(255,255,255,0.06); border-radius: 12px; padding: 0.9rem 1rem;
  }}
  .templates-save-row {{ display: flex; gap: 0.5rem; margin-bottom: 0.7rem; }}
  .templates-save-row input {{
    flex: 1; padding: 0.5rem 0.7rem; border-radius: 8px; border: 1px solid rgba(255,255,255,0.25);
    background: rgba(255,255,255,0.08); color: #fff; font-size: 0.85rem;
  }}
  .templates-save-row input::placeholder {{ color: #8891A5; }}
  .templates-save-row button {{
    background: var(--orange); color: #fff; border: none; padding: 0.5rem 0.9rem; border-radius: 8px;
    font-size: 0.8rem; font-weight: 700; cursor: pointer; white-space: nowrap;
  }}
  .templates-empty {{ color: #8891A5; font-size: 0.8rem; margin: 0.3rem 0; }}
  .template-row {{
    display: flex; align-items: center; justify-content: space-between; padding: 0.5rem 0;
    border-bottom: 1px solid rgba(255,255,255,0.1); font-size: 0.85rem;
  }}
  .template-row:last-child {{ border-bottom: none; }}
  .template-meta {{ display: block; color: #8891A5; font-size: 0.72rem; margin-top: 0.1rem; }}
  .template-row button {{
    background: none; border: 1px solid rgba(255,255,255,0.25); color: #fff; padding: 0.3rem 0.6rem;
    border-radius: 6px; font-size: 0.75rem; cursor: pointer; margin-left: 0.4rem;
  }}
  .template-row button.danger {{ border-color: var(--orange); color: var(--orange); }}

  .change-badge {{
    background: var(--orange); color: #fff; font-size: 0.75rem; font-weight: 700;
    padding: 0.35rem 0.7rem; border-radius: 999px; white-space: nowrap;
  }}

  .tabs-nav {{
    position: sticky; top: 0; z-index: 5; background: #fff; border-bottom: 1px solid #E4E7F0;
    display: flex; overflow-x: auto; padding: 0 0.6rem;
  }}
  .tab-btn {{
    border: none; background: none; padding: 0.85rem 0.9rem; font-size: 0.85rem; font-weight: 700;
    color: var(--muted); cursor: pointer; white-space: nowrap; border-bottom: 3px solid transparent;
  }}
  .tab-btn.active {{ color: var(--text-dark); border-bottom-color: var(--orange); }}

  main {{ max-width: 820px; margin: 1.2rem auto 0; padding: 0 1.2rem; }}
  .tab-panel {{ display: none; flex-direction: column; gap: 1.1rem; }}
  .tab-panel.active {{ display: flex; }}
  .panel-head {{ border-radius: 14px; padding: 1rem 1.3rem; }}
  .panel-head h2 {{ margin: 0 0 0.2rem; font-size: 1.15rem; }}
  .panel-head p {{ margin: 0; font-size: 0.82rem; color: var(--text-dark); opacity: 0.75; }}

  .card {{
    background: #fff; border-radius: 16px; box-shadow: 0 8px 24px rgba(16,19,26,0.08);
    overflow: hidden;
  }}
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
  .chk.single {{ display: inline-flex; }}
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

  /* 変更あり項目の強調(項目全体) */
  .field.changed {{
    background: var(--orange-tint); border-radius: 10px; box-shadow: inset 3px 0 0 var(--orange);
    padding-left: 0.8rem; margin-left: -0.8rem;
  }}
  tr.changed td {{ background: var(--orange-tint); }}

  /* モーター校正ウィジェット */
  .motor-widget {{
    padding: 0.9rem 0 1.3rem; border-bottom: 1px solid #EEF0F5; margin-bottom: 0.2rem;
  }}
  .motor-widget-head {{ display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.4rem; }}
  .motor-widget-head h3 {{ margin: 0; font-size: 0.98rem; }}
  .hw-badge {{ display: inline-block; padding: 0.25rem 0.6rem; border-radius: 999px; font-size: 0.72rem; font-weight: 700; }}
  .hw-on {{ background: #0F5132; color: #C7F0DA; }}
  .hw-off {{ background: var(--card-bg); color: var(--muted); cursor: help; }}
  .warning {{
    background: var(--orange-tint); border-radius: 10px; padding: 0.7rem 0.9rem; font-size: 0.8rem;
    color: var(--text-dark); line-height: 1.5; margin: 0.6rem 0 1rem;
  }}
  .slider-row {{ margin-bottom: 0.9rem; }}
  .slider-row label {{ display: flex; justify-content: space-between; font-weight: 700; font-size: 0.85rem; margin-bottom: 0.25rem; }}
  .slider-row input[type=range] {{ width: 100%; accent-color: var(--cyan); }}
  .motor-calib-block {{ margin-bottom: 1rem; }}
  .motor-calib-block h4 {{ margin: 0 0 0.5rem; font-size: 0.85rem; }}
  .raw-row {{ display: flex; gap: 0.5rem; align-items: center; margin-bottom: 0.6rem; }}
  .raw-row input[type=number] {{ flex: 1; }}
  .raw-row button {{
    background: var(--steel); color: #fff; border: none; padding: 0.55rem 0.9rem; border-radius: 8px;
    font-size: 0.8rem; font-weight: 700; cursor: pointer; white-space: nowrap;
  }}
  .lock-buttons {{ display: flex; gap: 0.5rem; flex-wrap: wrap; }}
  .lock-buttons button {{
    flex: 1; background: var(--card-bg); border: 1px solid #D8DCE6; color: var(--text-dark);
    padding: 0.5rem 0.65rem; border-radius: 8px; font-size: 0.76rem; font-weight: 700; cursor: pointer;
  }}
  .lock-buttons button:hover {{ background: #E9ECF3; }}
  button#motor-stop-btn {{
    background: var(--orange); color: #fff; border: none; padding: 0.6rem 1.2rem; border-radius: 999px;
    font-size: 0.85rem; font-weight: 700; cursor: pointer;
  }}

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

  /* 詳細設定 */
  details.advanced {{
    background: #fff; border-radius: 16px; box-shadow: 0 8px 24px rgba(16,19,26,0.06); padding: 0.2rem 1.2rem;
  }}
  details.advanced summary {{
    cursor: pointer; padding: 1rem 0; font-weight: 700; font-size: 0.9rem; color: var(--muted);
    list-style: none;
  }}
  details.advanced summary::-webkit-details-marker {{ display: none; }}
  details.advanced summary::before {{ content: "▸ "; color: var(--orange); }}
  details.advanced[open] summary::before {{ content: "▾ "; }}
  .adv-subsection {{ padding: 0 0 1.2rem; }}
  .adv-subsection h4 {{ margin: 0 0 0.5rem; font-size: 0.85rem; color: var(--text-dark); }}
  .adv-table {{ width: 100%; border-collapse: collapse; }}
  .adv-table td {{ padding: 0.5rem 0.4rem; border-bottom: 1px solid #F0F1F5; vertical-align: top; font-size: 0.85rem; }}
  .adv-table td:first-child {{ width: 34%; padding-top: 0.75rem; }}
  .adv-table code {{ font-size: 0.78rem; }}
  .adv-input {{
    width: 100%; padding: 0.4rem 0.6rem; border: 1px solid #D8DCE6; border-radius: 6px;
    font-family: "SF Mono", "Menlo", "Consolas", monospace; font-size: 0.8rem; background: #FBFBFD;
  }}
  .adv-input:focus {{ outline: 2px solid var(--cyan); outline-offset: 1px; border-color: var(--cyan); }}
  tr.readonly {{ opacity: 0.75; }}
  .code-readonly {{
    display: block; background: var(--card-bg); border-radius: 6px; padding: 0.4rem 0.6rem;
    font-family: "SF Mono", "Menlo", "Consolas", monospace; font-size: 0.78rem; color: var(--text-dark);
  }}

  /* コードログタブ */
  .codelog-category {{ margin-bottom: 1rem; }}
  .codelog-block {{ margin: 0 0 1.1rem; }}
  .codelog-title {{
    display: flex; justify-content: space-between; align-items: baseline;
    font-weight: 700; font-size: 0.82rem; color: var(--text-dark); margin-bottom: 0.35rem;
  }}
  .codelog-loc {{ font-weight: 400; font-size: 0.7rem; color: var(--muted); }}
  .codelog-pre {{
    background: var(--navy); color: #C7CEDE; border-radius: 8px; padding: 0.8rem 0.9rem;
    font-family: "SF Mono", "Menlo", "Consolas", monospace; font-size: 0.72rem; line-height: 1.55;
    overflow-x: auto; white-space: pre; margin: 0;
  }}

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
  <div class="header-top">
    <div>
      <div class="eyebrow">TOGIKAIDRIVE · CONFIG EDITOR</div>
      <h1>設定エディタ</h1>
      <p>config.py 全480項目を、ミニカーの処理カテゴリ別にまとめて安全に編集します。</p>
    </div>
    <div class="header-actions">
      <button id="reload-btn" class="ghost-btn" title="config.pyの内容が変わっていないか確認して再読み込みします">🔄 再読み込み</button>
      <button id="templates-btn" class="ghost-btn">📋 テンプレート</button>
    </div>
  </div>
  <div id="templates-panel" class="templates-panel" hidden>
    <div class="templates-save-row">
      <input type="text" id="template-name-input" placeholder="テンプレート名(例: 予選用)">
      <button id="template-save-btn">現在の設定を保存</button>
    </div>
    <div id="templates-list"></div>
  </div>
</header>
<nav class="tabs-nav">__TABS_NAV__</nav>
<div id="toast"></div>
<main>
__PANELS__
</main>
<div class="savebar">
  <span id="change-counter" class="change-badge" hidden></span>
  <span class="path">対象: __CONFIG_PATH__</span>
  <button id="save">変更を保存</button>
</div>
<script>
function switchTab(id) {{
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === id));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === 'panel-' + id));
}}

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
// (「よく使う設定」「詳細設定」どちらの項目にも同じ仕組みを使う)
// ---------------------------------------------------------------------
function formatLiteral(kind, value) {{
  if (kind === 'str' || kind === 'select' || kind === 'choice') return JSON.stringify(String(value));
  if (kind === 'int') {{
    const n = parseInt(value, 10);
    return String(Number.isFinite(n) ? n : value);
  }}
  if (kind === 'float') {{
    const n = parseFloat(value);
    return String(Number.isFinite(n) ? n : value);
  }}
  if (kind === 'bool') return value ? 'True' : 'False';
  if (kind === 'sensors') {{
    return '[' + value.map(v => JSON.stringify(v)).join(', ') + ']';
  }}
  if (kind === 'raw') return String(value);
  return JSON.stringify(String(value));
}}

function getCurrentValue(key) {{
  const meta = FIELD_META[key];
  const kind = meta ? meta.kind : null;
  if (kind === 'sensors') {{
    const group = document.querySelector(`.chk-group[data-key="${{key}}"]`);
    return Array.from(group.querySelectorAll('input[type=checkbox]:checked')).map(c => c.value);
  }}
  const el = document.querySelector(`[name="${{key}}"]`);
  if (!el) return null;
  if (kind === 'bool') return el.checked;
  return el.value;
}}

const CHANGED_KEYS = new Set();

function updateChangeCounter() {{
  const el = document.getElementById('change-counter');
  if (!el) return;
  if (CHANGED_KEYS.size === 0) {{
    el.hidden = true;
  }} else {{
    el.hidden = false;
    el.textContent = `変更: ${{CHANGED_KEYS.size}}件`;
  }}
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
  // meta.comment_raw はコメント前の元の空白をそのまま含む(行ごとにスペース数が
  // 違うことがあるため、ここで固定幅にすると値を変えていない行まで「変更あり」に
  // なってしまう)。
  const comment = meta.comment_raw || '';
  const newLine = meta.prefix + newLiteral + comment;
  const isChanged = newLine !== meta.full;

  // 項目全体(カード or 詳細設定の行)を目立たせる。差分プレビューは
  // 「入力・選択するたび」に、ここで毎回リアルタイムに更新される。
  const container = box.closest('.field') || box.closest('tr');
  if (container) container.classList.toggle('changed', isChanged);

  if (isChanged) {{
    CHANGED_KEYS.add(key);
    box.classList.add('changed');
    box.innerHTML = `<span class="code-loc">config.py ${{meta.line}}行目 (変更あり)</span>` +
      `<code class="code-old">${{escapeHtml(meta.full)}}</code>` +
      `<code class="code-new">${{escapeHtml(newLine)}}</code>`;
  }} else {{
    CHANGED_KEYS.delete(key);
    box.classList.remove('changed');
    box.innerHTML = `<span class="code-loc">config.py ${{meta.line}}行目</span><code class="code-cur">${{escapeHtml(meta.full)}}</code>`;
  }}
  updateChangeCounter();
}}

function escapeHtml(s) {{
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}}

// ---------------------------------------------------------------------
// モーター校正ウィジェット
// 確定ボタンは、値を直接 STEERING_CENTER_PWM 等の既存フィールドにセットして
// refreshCodePreview() を呼ぶだけ。専用の保存経路は持たず、ページ共通の
// 「変更を保存」フローにそのまま乗る。
// ---------------------------------------------------------------------
async function motorSendLive() {{
  const steering = parseFloat(document.getElementById('motor-steering-slider').value);
  const throttle = parseFloat(document.getElementById('motor-throttle-slider').value);
  document.getElementById('motor-steering-val').textContent = steering.toFixed(2);
  document.getElementById('motor-throttle-val').textContent = throttle.toFixed(2);
  try {{
    await fetch('/motor/live', {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{steering, throttle}}),
    }});
  }} catch (e) {{
    showToast('通信エラー: ' + e, true);
  }}
}}

async function motorStop() {{
  document.getElementById('motor-steering-slider').value = 0;
  document.getElementById('motor-throttle-slider').value = 0;
  document.getElementById('motor-steering-val').textContent = '0.00';
  document.getElementById('motor-throttle-val').textContent = '0.00';
  try {{
    await fetch('/motor/stop', {{method: 'POST'}});
    showToast('停止しました', false);
  }} catch (e) {{
    showToast('通信エラー: ' + e, true);
  }}
}}

async function motorTestRaw(axis) {{
  const input = document.getElementById('motor-' + axis + '-raw-input');
  const value = parseInt(input.value, 10);
  if (!Number.isFinite(value)) {{ showToast('数値を入力してください', true); return; }}
  try {{
    const res = await fetch('/motor/raw', {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}},
      body: JSON.stringify({{axis, value}}),
    }});
    const data = await res.json();
    if (!data.ok) showToast(data.message || '送信に失敗しました', true);
  }} catch (e) {{
    showToast('通信エラー: ' + e, true);
  }}
}}

function motorSetField(key, value) {{
  const el = document.querySelector(`[name="${{key}}"]`);
  if (!el) return;
  el.value = value;
  refreshCodePreview(key);
}}

function motorLockSteeringCenter() {{
  const v = parseInt(document.getElementById('motor-steering-raw-input').value, 10);
  if (!Number.isFinite(v)) {{ showToast('先に値を送信してテストしてください', true); return; }}
  motorSetField('STEERING_CENTER_PWM', v);
  showToast('ステアリング中央を ' + v + ' に設定しました(まだ保存されていません)', false);
}}

function motorLockSteeringExtreme() {{
  const v = parseInt(document.getElementById('motor-steering-raw-input').value, 10);
  if (!Number.isFinite(v)) {{ showToast('先に値を送信してテストしてください', true); return; }}
  const centerEl = document.querySelector('[name="STEERING_CENTER_PWM"]');
  const center = centerEl ? parseInt(centerEl.value, 10) : NaN;
  if (!Number.isFinite(center)) {{ showToast('先に中央を設定してください', true); return; }}
  const width = Math.abs(v - center);
  motorSetField('STEERING_WIDTH_PWM', width);
  showToast('振れ幅を ' + width + ' に設定しました(まだ保存されていません)', false);
}}

function motorLockThrottle(kind) {{
  const v = parseInt(document.getElementById('motor-throttle-raw-input').value, 10);
  if (!Number.isFinite(v)) {{ showToast('先に値を送信してテストしてください', true); return; }}
  motorSetField('THROTTLE_' + kind + '_PWM', v);
  showToast('設定しました: ' + v + '(まだ保存されていません)', false);
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
  [[42, 62], [164, 62], [42, 282], [164, 282]].forEach(([x, y]) => {{
    svg.appendChild(el('rect', {{x, y, width: 14, height: 34, rx: 4, class: 'car-wheel'}}));
  }});
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

// ---------------------------------------------------------------------
// 保存
// ---------------------------------------------------------------------
function collectValues() {{
  const values = {{}};
  document.querySelectorAll('[data-kind]').forEach(el => {{
    const kind = el.dataset.kind;
    if (kind === 'sensors') {{
      const key = el.dataset.key;
      values[key] = Array.from(el.querySelectorAll('input[type=checkbox]:checked')).map(c => c.value);
    }} else if (kind === 'bool') {{
      values[el.name] = el.checked;
    }} else {{
      values[el.name] = el.value;
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
      showToast('保存しました（バックアップ: ' + data.backup + '）。反映のため再読み込みします…', false);
      // 保存後は値がconfig.pyの新しい基準値になるため、ページごと再読み込みして
      // 差分プレビュー・変更件数カウンターをまっさらな状態に揃える
      setTimeout(() => location.reload(), 1000);
      return;
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

// ---------------------------------------------------------------------
// 再読み込み(キャッシュのハッシュ確認)
// ---------------------------------------------------------------------
document.getElementById('reload-btn').addEventListener('click', async () => {{
  try {{
    const res = await fetch('/reload');
    const data = await res.json();
    showToast(
      data.regenerated ? 'config.pyの変更を検知し、再読み込みしました' : '変更なし（キャッシュを利用しています）',
      false
    );
    setTimeout(() => location.reload(), 900);
  }} catch (e) {{
    showToast('再読み込みに失敗しました: ' + e, true);
  }}
}});

// ---------------------------------------------------------------------
// テンプレート(現在の設定を任意名で保存・一覧・適用・削除)
// ---------------------------------------------------------------------
document.getElementById('templates-btn').addEventListener('click', () => {{
  const panel = document.getElementById('templates-panel');
  panel.hidden = !panel.hidden;
  if (!panel.hidden) loadTemplates();
}});

async function loadTemplates() {{
  const list = document.getElementById('templates-list');
  list.innerHTML = '<p class="templates-empty">読み込み中…</p>';
  try {{
    const res = await fetch('/templates');
    const data = await res.json();
    if (!data.templates.length) {{
      list.innerHTML = '<p class="templates-empty">まだテンプレートがありません</p>';
      return;
    }}
    list.innerHTML = data.templates.map(t => `
      <div class="template-row">
        <div><strong>${{escapeHtml(t.name)}}</strong><span class="template-meta">${{escapeHtml(t.saved_at)}}</span></div>
        <div>
          <button onclick="applyTemplate('${{escapeHtml(t.name)}}')">適用</button>
          <button class="danger" onclick="deleteTemplate('${{escapeHtml(t.name)}}')">削除</button>
        </div>
      </div>
    `).join('');
  }} catch (e) {{
    list.innerHTML = '<p class="templates-empty">読み込みに失敗しました</p>';
  }}
}}

document.getElementById('template-save-btn').addEventListener('click', async () => {{
  const nameInput = document.getElementById('template-name-input');
  const name = nameInput.value.trim();
  if (!name) {{ showToast('テンプレート名を入力してください', true); return; }}
  try {{
    const res = await fetch('/templates/save', {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{name}}),
    }});
    const data = await res.json();
    if (data.ok) {{
      showToast(`テンプレート「${{name}}」を保存しました`, false);
      nameInput.value = '';
      loadTemplates();
    }} else {{
      showToast(data.message || '保存に失敗しました', true);
    }}
  }} catch (e) {{
    showToast('通信エラー: ' + e, true);
  }}
}});

async function applyTemplate(name) {{
  if (!confirm(`テンプレート「${{name}}」を適用します。現在のconfig.pyの内容は上書きされます(直前の状態はバックアップされます)。よろしいですか？`)) return;
  try {{
    const res = await fetch('/templates/apply', {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{name}}),
    }});
    const data = await res.json();
    if (data.ok) {{
      showToast('適用しました（バックアップ: ' + data.backup + '）', false);
      setTimeout(() => location.reload(), 900);
    }} else {{
      showToast(data.message || '適用に失敗しました', true);
    }}
  }} catch (e) {{
    showToast('通信エラー: ' + e, true);
  }}
}}

async function deleteTemplate(name) {{
  if (!confirm(`テンプレート「${{name}}」を削除します。よろしいですか？`)) return;
  try {{
    const res = await fetch('/templates/delete', {{
      method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{name}}),
    }});
    const data = await res.json();
    if (data.ok) {{
      showToast('削除しました', false);
      loadTemplates();
    }} else {{
      showToast(data.message || '削除に失敗しました', true);
    }}
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
class Handler(BaseHTTPRequestHandler):
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

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = render_page().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            # 毎回config.pyを読み直して最新値を表示する設計なので、ブラウザ側の
            # HTTPキャッシュで古いページが再利用されないようにする
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/reload":
            _snap, regenerated = get_snapshot(force=False)
            self._send_json(200, dict(ok=True, regenerated=regenerated))
        elif self.path == "/templates":
            self._send_json(200, dict(ok=True, templates=list_templates()))
        elif self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        try:
            posted = self._read_json_body()

            if self.path == "/save":
                snap, _ = get_snapshot()
                field_defs = snap["field_defs"]
                new_values = {}
                kinds = {}
                for key, value in posted.items():
                    field = field_defs.get(key)
                    if not field:
                        continue  # 未知のキーは無視(古いページ/改ざん対策)
                    kind = field["kind"]
                    new_values[key] = validate(kind, key, value, field)
                    kinds[key] = kind
                backup = write_values(new_values, kinds, field_defs)
                get_snapshot(force=True)  # 書き込み直後にキャッシュを作り直しておく
                self._send_json(200, dict(ok=True, backup=backup.name))

            elif self.path == "/templates/save":
                name = save_template(posted.get("name", ""))
                self._send_json(200, dict(ok=True, name=name))

            elif self.path == "/templates/apply":
                backup = apply_template(posted.get("name", ""))
                self._send_json(200, dict(ok=True, backup=backup.name))

            elif self.path == "/templates/delete":
                delete_template(posted.get("name", ""))
                self._send_json(200, dict(ok=True))

            elif self.path == "/motor/live":
                steering = max(-1.0, min(1.0, float(posted.get("steering", 0))))
                throttle = max(-1.0, min(1.0, float(posted.get("throttle", 0))))
                motor_instance.set_steering_pwm_value(steering)
                motor_instance.set_throttle_pwm_value(throttle)
                self._send_json(200, dict(ok=True))

            elif self.path == "/motor/raw":
                axis = posted.get("axis")
                value = int(posted.get("value"))
                lo, hi = MOTOR_RAW_PWM_RANGE
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

            elif self.path == "/motor/stop":
                motor_instance.set_steering_pwm_value(0)
                motor_instance.set_throttle_pwm_value(0)
                self._send_json(200, dict(ok=True))

            else:
                self.send_response(404)
                self.end_headers()

        except ValueError as e:
            self._send_json(400, dict(ok=False, message=str(e)))
        except Exception as e:  # noqa: BLE001
            self._send_json(500, dict(ok=False, message=f"予期しないエラー: {e}"))


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

    TEMPLATES_DIR.mkdir(exist_ok=True)
    get_snapshot(force=True)  # 起動時にキャッシュを作成しておく
    init_motor()

    with ThreadingHTTPServer(("0.0.0.0", PORT), Handler) as httpd:
        print("=" * 60)
        print("togikaidrive 設定エディタ を起動しました")
        print(f"  対象ファイル: {CONFIG_PATH}")
        print(f"  キャッシュ:    作成完了")
        print(f"  モーター:      {'実機接続' if HARDWARE_AVAILABLE else 'モック(シミュレーション)'}")
        print(f"  テンプレート: {TEMPLATES_DIR}")
        print(f"  ローカル:      http://localhost:{PORT}")
        print(f"  同一ネットワーク: http://{local_ip()}:{PORT}")
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
