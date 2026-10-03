"""
togikaidrive-tools 共通: 実行環境のチェックと、分かりやすい案内メッセージ
==========================================================================
他のメンバーのPCに配布した時に、「Pythonのエラー文(FileNotFoundErrorなど)が出て
何が悪いのか分からない」状態にならないための部品。

- togikaidrive-dev(車本体のコード。外部リポジトリで、このツールの配布物には含まれない)
  の場所を探す。見つからない場合は、置き場所を日本語で案内して終了する。
- ライブラリ不足(ModuleNotFoundError)のログから、入れるべきライブラリと
  pipコマンドを案内する。
"""
from __future__ import annotations

import os
import re
from pathlib import Path

DEV_DIR_NAME = "togikaidrive-dev"
DEV_DIR_ENV = "TOGIKAIDRIVE_DEV_DIR"


def find_togikaidrive_dev(repo_root: Path) -> Path | None:
    """togikaidrive-devのフォルダ(config.pyがあるフォルダ)を探す。見つからなければNone。

    探す順番:
      1. 環境変数 TOGIKAIDRIVE_DEV_DIR(置き場所を自由にしたい場合の逃げ道)
      2. repo_root/togikaidrive-dev        (lab/ と同じ場所)
      3. repo_root の隣/togikaidrive-dev   (ツールのフォルダと並べて置いた場合)
      4. 上の2か所にある「togikaidrive-dev」で始まる名前のフォルダ
         (GitHubのZIPで取得すると togikaidrive-dev-main という名前になるため)
    """
    env = os.environ.get(DEV_DIR_ENV)
    if env and (Path(env) / "config.py").is_file():
        return Path(env)
    bases = [repo_root, repo_root.parent]
    for base in bases:
        if (base / DEV_DIR_NAME / "config.py").is_file():
            return base / DEV_DIR_NAME
    for base in bases:
        try:
            children = sorted(base.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_dir() and child.name.startswith(DEV_DIR_NAME) and (child / "config.py").is_file():
                return child
    return None


def resolve_togikaidrive_dev(repo_root: Path) -> Path:
    """見つからなくても終了せず、「ここにあるはず」というパスを返す(存在確認は呼び出し側)。
    togikaidrive-devが無くても起動自体はできるべき共通部品(shared/配下)向け。"""
    return find_togikaidrive_dev(repo_root) or (repo_root / DEV_DIR_NAME)


def require_togikaidrive_dev(repo_root: Path) -> Path:
    """togikaidrive-devが必須のツール向け。見つからなければ、置き場所を案内して終了する。"""
    found = find_togikaidrive_dev(repo_root)
    if found is not None:
        return found
    print("=" * 64)
    print("❌ togikaidrive-dev(車本体のコード)が見つかりません。")
    print()
    print("このツールは togikaidrive-dev の config.py などを読み書きします。")
    print("次のどちらかの場所に、togikaidrive-dev フォルダを置いてから、もう一度起動してください。")
    print(f"  1. {repo_root / DEV_DIR_NAME}")
    print("       (このツールの README.md や「ポータルを起動」ファイルと同じ場所)")
    print(f"  2. {repo_root.parent / DEV_DIR_NAME}")
    print("       (このツールのフォルダのすぐ隣)")
    print()
    print("・フォルダ名が「togikaidrive-dev-main」のようになっていても自動で見つけますが、")
    print("  config.py がそのフォルダの直下にあることを確認してください")
    print("  (展開したフォルダの中にもう1つ同名のフォルダがある場合は、内側の方を使います)。")
    print(f"・置き場所を変えたくない場合は、環境変数 {DEV_DIR_ENV} にフォルダの場所を指定できます。")
    print("=" * 64)
    raise SystemExit(1)


# import名と、pipで入れる時のパッケージ名が違うもの
_PIP_NAME = {
    "cv2": "opencv-python", "yaml": "pyyaml", "PIL": "pillow", "sklearn": "scikit-learn",
    "Adafruit_PCA9685": "Adafruit-PCA9685", "serial": "pyserial", "dateutil": "python-dateutil",
}
_MISSING_MODULE = re.compile(r"No module named '([A-Za-z0-9_.]+)'")


def missing_module_hint(log_text: str, python_exe: str, requirements: Path | None = None) -> str | None:
    """ログに ModuleNotFoundError があれば、入れるべきライブラリとコマンドの案内を返す。
    requirements に requirements.txt があれば、まとめて入れるコマンドも添える。無ければNone。"""
    m = _MISSING_MODULE.search(log_text or "")
    if not m:
        return None
    module = m.group(1).split(".")[0]
    package = _PIP_NAME.get(module, module)
    lines = [f"ライブラリ「{module}」が入っていないため実行できませんでした。",
             f"  → {python_exe} -m pip install {package}"]
    if requirements is not None and requirements.is_file():
        lines.append(f"  → まとめて入れる場合: {python_exe} -m pip install -r \"{requirements}\"")
    lines.append("(入れたあと、もう一度実行してください。ライブラリは実行するPython(上のコマンドのPython)に入れる必要があります)")
    return "\n".join(lines)
