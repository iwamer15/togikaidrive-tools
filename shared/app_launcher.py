"""
togikaidrive-tools 共通: 外部デスクトップアプリの起動ヘルパー
================================================================
`annotation_training_d2j`(画像アノテーション・学習管理用のPyQt5デスクトップアプリ、
`togikaidrive-dev/annotation_training_d2j/main.py`)は独自のWeb機能を持たない
モノリシックなデスクトップアプリのため、書き直さずにサブプロセスとして起動するだけの
薄い連携にする。ポータルのトップレベルタブ(アノテーションツールランチャー)と、
config-editorに埋め込まれる画像学習パネルの両方から同じ関数を呼び、起動処理を
二重実装しない。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOLS_ROOT = HERE.parent  # ト技会-minicar/ 直下
ANNOTATION_TOOL_DIR = TOOLS_ROOT / "togikaidrive-dev" / "annotation_training_d2j"
ANNOTATION_TOOL_MAIN = ANNOTATION_TOOL_DIR / "main.py"

# このプロセス(ポータル/各ツールのhttp.serverプロセス)が起動したアノテーションツールの
# 参照。プロセスを跨いだ検知はしない(単一のローカルツールが自分で起動したものだけを
# 把握できれば、二重起動の誤クリック防止としては十分なため)。
_LAUNCHED_PROC: subprocess.Popen | None = None


def _annotation_python_exe() -> str:
    """annotation_training_d2j専用のvenvがあればそれを使い、無ければ
    このサーバーを動かしているPythonにフォールバックする
    (training-execution-toolのtogikaidrive-dev/venv検出と同じパターン)。"""
    venv_python = ANNOTATION_TOOL_DIR / "venv" / "bin" / "python3"
    return str(venv_python) if venv_python.exists() else sys.executable


def annotation_tool_available() -> bool:
    return ANNOTATION_TOOL_MAIN.exists()


def launch_status() -> dict:
    """このサーバーが起動したアノテーションツールが今も動いているかを返す。"""
    proc = _LAUNCHED_PROC
    running = proc is not None and proc.poll() is None
    return dict(running=running, pid=(proc.pid if running else None))


def launch_annotation_tool() -> dict:
    """annotation_training_d2j/main.py をサブプロセスとして起動する。
    既にこのサーバーから起動済みでまだ動いている場合は、再起動せず
    `already_running=True` を返す(誤って複数ウィンドウを開かせないため)。"""
    global _LAUNCHED_PROC

    if not ANNOTATION_TOOL_MAIN.exists():
        return dict(ok=False, message=f"アノテーションツールが見つかりません: {ANNOTATION_TOOL_MAIN}")

    status = launch_status()
    if status["running"]:
        return dict(ok=True, already_running=True, pid=status["pid"])

    python_exe = _annotation_python_exe()
    try:
        proc = subprocess.Popen(
            [python_exe, "main.py"],
            cwd=str(ANNOTATION_TOOL_DIR),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:  # noqa: BLE001
        return dict(ok=False, message=f"起動に失敗しました: {e}")

    _LAUNCHED_PROC = proc
    return dict(ok=True, already_running=False, pid=proc.pid)


def read_session_summary() -> dict | None:
    """annotation_training_d2j/sessions/session.json があれば軽く要約して返す。
    形式は把握しきれていない前提で、あくまで参考表示用にベストエフォートで読む。
    存在しない・読めない場合はNoneを返す(このツールの主目的である起動リンクの
    妨げにならないよう、失敗を握りつぶす)。"""
    session_path = ANNOTATION_TOOL_DIR / "sessions" / "session.json"
    if not session_path.exists():
        return None
    try:
        import json

        data = json.loads(session_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return dict(
        path=str(session_path),
        mtime=session_path.stat().st_mtime,
        keys=sorted(data.keys()) if isinstance(data, dict) else [],
    )
