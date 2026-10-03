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

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from . import env_check

HERE = Path(__file__).resolve().parent
TOOLS_ROOT = HERE.parent  # lab/
REPO_ROOT = TOOLS_ROOT.parent  # ト技会-minicar/ (togikaidrive-dev/ がある場所)
ANNOTATION_TOOL_DIR = env_check.resolve_togikaidrive_dev(REPO_ROOT) / "annotation_training_d2j"
ANNOTATION_TOOL_MAIN = ANNOTATION_TOOL_DIR / "main.py"
# Windowsには/tmpが無いので、OS標準の一時フォルダを使う
ANNOTATION_TOOL_LOG = Path(tempfile.gettempdir()) / "togikai-annotation-tool.log"

# 起動直後にクラッシュしたかどうかを判定するために、Popen後どれだけ待つか(秒)。
# torch/PyQt5の初回読み込みは数秒かかることがあるが、Qtプラグインが見つからない等の
# 起動失敗は数秒以内に(ウィンドウを出す前に)プロセスが終了するので、この程度で十分見分けられる。
_STARTUP_CHECK_SECONDS = 3.0

# このプロセス(ポータル/各ツールのhttp.serverプロセス)が起動したアノテーションツールの
# 参照。プロセスを跨いだ検知はしない(単一のローカルツールが自分で起動したものだけを
# 把握できれば、二重起動の誤クリック防止としては十分なため)。
_LAUNCHED_PROC: subprocess.Popen | None = None


def _annotation_python_exe() -> str:
    """annotation_training_d2j専用のvenvがあればそれを使い、無ければ
    このサーバーを動かしているPythonにフォールバックする
    (training-execution-toolのtogikaidrive-dev/venv検出と同じパターン)。"""
    # Mac/Linuxは venv/bin/python3、Windowsは venv/Scripts/python.exe
    for rel in (("bin", "python3"), ("Scripts", "python.exe")):
        venv_python = ANNOTATION_TOOL_DIR / "venv" / Path(*rel)
        if venv_python.exists():
            return str(venv_python)
    return sys.executable


def annotation_tool_available() -> bool:
    return ANNOTATION_TOOL_MAIN.exists()


def _launch_env() -> dict:
    """annotation_training_d2j をサブプロセス起動する際の環境変数を組み立てる。

    Qtプラグインパス:
        PyQt5がmacOS用の描画プラグイン(cocoa)を自力で見つけられず、ウィンドウを
        出す前に`qt.qpa.plugin: Could not find the Qt platform plugin "cocoa"`で
        即終了することがある(annotation_training_d2jのvenvで実際に発生を確認済み)。
        そのvenvにバンドルされているプラグインディレクトリを明示的に渡すことで防ぐ。

        venvの`bin/python3`はvenv外の実体(システムのPython本体)へのシンボリックリンクに
        なっていることが多く、`Path.resolve()`で実体を辿ると`venv/lib/...`自体を
        見失ってしまう(実際に発生を確認済み)。そのため実行ファイルからではなく、
        ANNOTATION_TOOL_DIR直下の`venv/`という既知の場所から直接探す。
        見つからない場合(venvが無い/Windows/Linuxや別レイアウトのPyQt5)は何も追加しない。

    COLAB_ENABLED:
        Colab連携(colab/config_colab.py)は環境変数でしか有効化できず、アプリ内の
        チェックボックスは表示のみで実際の有効/無効を切り替えない。ポータンからの
        起動でもColab連携メニューを使えるよう、既定でtrueを渡す
        (呼び出し元が明示的に指定していれば上書きしない)。"""
    env = dict(os.environ)
    env.setdefault("COLAB_ENABLED", "true")

    if "QT_QPA_PLATFORM_PLUGIN_PATH" not in env:
        venv_lib = ANNOTATION_TOOL_DIR / "venv" / "lib"
        for candidate in venv_lib.glob("python3*/site-packages/PyQt5/Qt*/plugins/platforms"):
            if (candidate / "libqcocoa.dylib").exists() or any(candidate.glob("*cocoa*")):
                env["QT_QPA_PLATFORM_PLUGIN_PATH"] = str(candidate)
                break
    return env


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
        log_file = ANNOTATION_TOOL_LOG.open("w", encoding="utf-8")
        proc = subprocess.Popen(
            [python_exe, "-u", "main.py"],
            cwd=str(ANNOTATION_TOOL_DIR),
            env=_launch_env(),
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
    except Exception as e:  # noqa: BLE001
        return dict(ok=False, message=f"起動に失敗しました: {e}")

    # PyQt5のプラグイン未検出などは、ウィンドウを出す前(数秒以内)にプロセスが
    # 終了する形で失敗する。Popen()自体は成功する(プロセスの起動そのものはできている)ため、
    # 少し待って本当に生きているかを確認しないと「起動しました」という誤表示になる。
    time.sleep(_STARTUP_CHECK_SECONDS)
    if proc.poll() is not None:
        log_file.close()
        tail = ""
        try:
            tail = ANNOTATION_TOOL_LOG.read_text(encoding="utf-8", errors="replace")[-800:]
        except OSError:
            pass
        hint = env_check.missing_module_hint(
            tail, python_exe, ANNOTATION_TOOL_DIR / "requirements.txt")
        if hint:
            return dict(ok=False, message=hint)
        return dict(ok=False, message=f"起動直後に終了しました(終了コード{proc.returncode})。ログ: {tail.strip()[-400:]}")

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
