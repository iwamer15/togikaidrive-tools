#!/usr/bin/env python3
"""
ラズパイ実機制御エディタ
========================
ラズパイ上で動かす、実機(PCA9685・モーター・サーボ)に触れる専用の設定エディタの入口。

中身は`togikaidrive-config-editor`をそのまま使い(コードは複製しない)、実機制御用として
起動したことを画面に出すための`UI_MODE = "raspi"`だけを設定して起動する。
ポータルの設定エディタとほぼ同じ画面になるため、取り違え防止として、実機に繋がっている間は
赤い帯・赤いヘッダー・「実機制御エディタ」というタイトルで表示される(見た目の判定は
設定エディタ側の`_mode_labels()`)。

通常は手動で起動せず、ポータルの「🍓 ラズパイ実機」タブ(raspi-control-tool)から
配置・起動・停止する。手動で起動する場合(ラズパイ上で):
    cd lab/raspi-editor
    ~/togikaidrive-dev/venv/bin/python3 server.py --no-ml
    → http://<ラズパイのIP>:8899
`--no-ml`はtorch等の重い読み込み(判断ロジック・YOLO)を省く軽量起動で、モーター校正だけなら数秒で立ち上がる。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS_ROOT = HERE.parent  # lab/ (兄弟ツールとshared/がある場所)

# 同名(server.py)の兄弟ツールを`import server`すると、この入口自身を読み込んでしまうため、
# 一意な名前でファイルから読み込む(togikaidrive-portalと同じ手法)。
_spec = importlib.util.spec_from_file_location(
    "togikaidrive_config_editor_for_raspi", TOOLS_ROOT / "togikaidrive-config-editor" / "server.py")
config_editor = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = config_editor
_spec.loader.exec_module(config_editor)

config_editor.UI_MODE = "raspi"

if __name__ == "__main__":
    config_editor.main()
