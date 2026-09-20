"""
togikaidrive-tools 共通 SSH/ラズパイ連携モジュール
====================================================
設定エディタ・前処理ツール・学習実行ツールが共通で使う、「ラズパイとこのMacの間で
ファイルをやり取りする」ためだけのモジュール。config.py/catalog/学習モデルといった
各ツール固有の知識は一切持たない(呼び出し側がパスを渡す)。

- 追加のpipライブラリは使わない。システムの`ssh`/`rsync`(OpenSSHクライアント。
  macOS/ラズパイOS双方に標準搭載)をsubprocessで呼び出すだけ。
- パスワード認証はサポートしない(`BatchMode=yes`を常に付け、鍵認証が使えない場合は
  パスワード入力待ちで固まらず即座にエラーになるようにする)。
- 実行するリモートコマンドはすべて、呼び出し側が渡す固定の値(ディレクトリ名の
  ホワイトリスト等)からこのファイル内で組み立てたものだけで、外部からの自由な
  コマンド入力は受け付けない。
- 接続情報(ホスト名・ユーザー名・鍵ファイルパス・ラズパイ上のtogikaidrive-devの
  場所)は、3ツール共通のローカルJSON(shared/ssh_connection.json、.gitignore済み)
  に保存する。
"""
from __future__ import annotations

import difflib
import json
import posixpath
import re
import shlex
import shutil
import subprocess
from pathlib import Path

SSH_CONNECTION_PATH = Path(__file__).resolve().parent / "ssh_connection.json"
_DEFAULT_CONNECTION = dict(host="", user="pi", port=22, identity_file="", remote_base_dir="")
_SAFE_ENTRY_NAME = re.compile(r"[A-Za-z0-9_.\-]+")


# ---------------------------------------------------------------------------
# 接続設定の読み書き
# ---------------------------------------------------------------------------
def load_connection() -> dict:
    if not SSH_CONNECTION_PATH.is_file():
        return dict(_DEFAULT_CONNECTION)
    try:
        data = json.loads(SSH_CONNECTION_PATH.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001  -- 壊れたJSONの場合はデフォルトに戻す
        return dict(_DEFAULT_CONNECTION)
    conn = dict(_DEFAULT_CONNECTION)
    conn.update({k: data[k] for k in _DEFAULT_CONNECTION if k in data})
    if not conn["remote_base_dir"] and data.get("remote_config_path"):
        # 旧スキーマ(config.py単体のパスだけを保存していた頃のssh_connection.json)
        # からの自動移行。次にsave_connection()するまでファイルは書き換えない。
        conn["remote_base_dir"] = posixpath.dirname(data["remote_config_path"])
    return conn


def save_connection(data: dict) -> dict:
    conn = dict(_DEFAULT_CONNECTION)
    conn["host"] = str(data.get("host", "")).strip()
    conn["user"] = str(data.get("user", "pi")).strip() or "pi"
    try:
        conn["port"] = int(data.get("port") or 22)
    except (TypeError, ValueError):
        raise ValueError("ポート番号は整数で入力してください")
    conn["identity_file"] = str(data.get("identity_file", "")).strip()
    conn["remote_base_dir"] = str(data.get("remote_base_dir", "")).strip().rstrip("/")
    if not conn["host"]:
        raise ValueError("ホスト名(またはIPアドレス)を入力してください")
    if not conn["remote_base_dir"]:
        raise ValueError("ラズパイ上のtogikaidrive-devのパスを入力してください")
    SSH_CONNECTION_PATH.parent.mkdir(parents=True, exist_ok=True)
    SSH_CONNECTION_PATH.write_text(json.dumps(conn, ensure_ascii=False, indent=2), encoding="utf-8")
    return conn


# ---------------------------------------------------------------------------
# SSH実行の基礎
# ---------------------------------------------------------------------------
def ssh_base_args(conn: dict) -> list:
    if not conn.get("host"):
        raise ValueError("先に接続設定(ホスト名)を保存してください")
    ssh_bin = shutil.which("ssh")
    if not ssh_bin:
        raise ValueError("sshコマンドが見つかりません(OpenSSHクライアントが必要です)")
    args = [ssh_bin, "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
            "-o", "StrictHostKeyChecking=accept-new", "-p", str(conn.get("port") or 22)]
    if conn.get("identity_file"):
        args += ["-i", conn["identity_file"]]
    args.append(f"{conn.get('user') or 'pi'}@{conn['host']}")
    return args


def run_ssh(conn: dict, remote_command: str, input_bytes: bytes | None = None, timeout: int = 15):
    """remote_command は呼び出し側が固定で組み立てた文字列のみを渡すこと
    (ユーザーの自由入力をそのまま渡さない)。"""
    args = ssh_base_args(conn) + [remote_command]
    try:
        proc = subprocess.run(args, input=input_bytes, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ValueError("接続がタイムアウトしました(ホスト名・ポート・電源・鍵認証の設定を確認してください)")
    except FileNotFoundError:
        raise ValueError("sshコマンドの実行に失敗しました")
    return proc.returncode, proc.stdout, proc.stderr


def test_connection(conn: dict) -> dict:
    code, out, err = run_ssh(conn, "echo OK && hostname && (python3 --version 2>&1)")
    if code != 0:
        raise ValueError(f"接続に失敗しました: {err.decode('utf-8', 'replace').strip() or '(詳細不明。SSH鍵認証が設定されているか確認してください)'}")
    return dict(message=out.decode("utf-8", "replace").strip())


# ---------------------------------------------------------------------------
# 単一テキストファイルの相互反映(config.pyのような「1ファイル丸ごと」向け)
# ---------------------------------------------------------------------------
def backup_file(path: Path) -> Path:
    import datetime
    backup_path = path.with_name(f"{path.name}.bak.{datetime.datetime.now():%Y%m%d_%H%M%S}")
    shutil.copy2(path, backup_path)
    return backup_path


def fetch_remote_text(conn: dict, remote_path: str) -> str:
    if not remote_path:
        raise ValueError("ラズパイ上のファイルパスを指定してください")
    code, out, err = run_ssh(conn, f"cat {shlex.quote(remote_path)}")
    if code != 0:
        raise ValueError(f"リモートのファイルを取得できませんでした: {err.decode('utf-8', 'replace').strip()}")
    return out.decode("utf-8", "replace")


def diff_text(local_text: str, remote_text: str,
              local_label: str = "ローカル(このMac)", remote_label: str = "ラズパイ") -> dict:
    diff_lines = list(difflib.unified_diff(
        local_text.splitlines(), remote_text.splitlines(),
        fromfile=local_label, tofile=remote_label, lineterm="",
    ))
    return dict(diff=diff_lines, identical=(local_text == remote_text))


def push_text_file(conn: dict, local_path: Path, remote_path: str) -> str:
    """local_pathの内容をそのままremote_pathに書き込む。書き込み前に必ずリモート側も
    <ファイル名>.bak.<日時> にバックアップしてから上書きする。scpに依存せず、
    `cat > path` にローカルのバイト列を標準入力で流し込むことで1回のssh呼び出し
    だけで完結させる。"""
    if not remote_path:
        raise ValueError("ラズパイ上のファイルパスを指定してください")
    import datetime
    local_bytes = local_path.read_bytes()
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    quoted = shlex.quote(remote_path)
    remote_cmd = f"test -f {quoted} && cp {quoted} {quoted}.bak.{ts}; cat > {quoted}"
    code, _out, err = run_ssh(conn, remote_cmd, input_bytes=local_bytes)
    if code != 0:
        raise ValueError(f"ラズパイへの反映に失敗しました: {err.decode('utf-8', 'replace').strip()}")
    return f"{posixpath.basename(remote_path)}.bak.{ts}"


def pull_text_file(conn: dict, remote_path: str, local_path: Path) -> Path:
    """remote_pathの内容でlocal_pathを上書きする。書き込み前に必ずローカルも
    backup_file()でバックアップする。"""
    remote_text = fetch_remote_text(conn, remote_path)
    backup_path = backup_file(local_path)
    local_path.write_text(remote_text, encoding="utf-8")
    return backup_path


# ---------------------------------------------------------------------------
# ディレクトリ監査(大量ファイル・大容量のフォルダ向け。ローカル ⇔ ラズパイ 比較・同期)
# config.pyのような1ファイルは丸ごと上書きでも安全だが、data/models配下のように
# 大量ファイル・大容量なフォルダは同じやり方をしない。常に
#   1. まず読み取り専用で「どのフォルダ/ファイルがローカルのみ・ラズパイのみ・
#      両方にあるが中身が違う・一致」かを一覧表示する(監査)
#   2. 一致しない項目だけ、フォルダ/ファイル単位で明示的にpull/pushする
# という2段構えにし、削除は一切行わない(rsyncに --delete を付けない。
# 転送は常に「追加・更新」のみ)。
# 監査対象ディレクトリ名(dirs)は呼び出し側が固定リストで渡すことが前提で、
# ユーザー入力で任意のパスを指定させることはしない。転送対象のエントリ名は
# 都度、英数字・._-のみの安全な文字列であることを検証してから使う
# (パストラバーサル対策)。
# ---------------------------------------------------------------------------
def list_local_dir_entries(local_base: Path, dir_name: str) -> dict:
    """ローカルの <local_base>/<dir_name> 直下の各エントリについて、
    種別・合計バイト数(ディレクトリは再帰合計)・ファイル数・更新日時を返す。"""
    base = local_base / dir_name
    entries = {}
    if not base.is_dir():
        return entries
    for child in base.iterdir():
        if child.name.startswith("."):
            continue  # .DS_Store等は監査対象外
        try:
            if child.is_dir():
                total = 0
                count = 0
                for p in child.rglob("*"):
                    if p.is_file():
                        total += p.stat().st_size
                        count += 1
                mtime = child.stat().st_mtime
                entries[child.name] = dict(type="dir", size=total, count=count, mtime=mtime)
            else:
                st = child.stat()
                entries[child.name] = dict(type="file", size=st.st_size, count=1, mtime=st.st_mtime)
        except OSError:
            continue  # 権限エラー等はスキップ(監査全体は止めない)
    return entries


def list_remote_dir_entries(conn: dict, remote_base_dir: str, dir_name: str) -> dict:
    """list_local_dir_entriesのラズパイ版。固定のシェルスニペットを1回のssh呼び出しで
    実行し、"種別\\t名前\\tバイト数\\tファイル数\\t更新日時(epoch秒)"を1行ずつ返させる。
    dir_nameは呼び出し側の固定リストの値のみを渡す前提(呼び出し側で検証済み)。"""
    remote_dir = posixpath.join(remote_base_dir, dir_name)
    quoted_dir = shlex.quote(remote_dir)
    script = (
        f"[ -d {quoted_dir} ] || exit 0; "
        f"for f in {quoted_dir}/*; do "
        '[ -e "$f" ] || continue; '
        'name=$(basename "$f"); '
        'case "$name" in .*) continue;; esac; '
        'if [ -d "$f" ]; then '
        "  sz=$(find \"$f\" -type f -printf '%s\\n' 2>/dev/null | awk '{s+=$1} END{print s+0}'); "
        '  cnt=$(find "$f" -type f 2>/dev/null | wc -l | tr -d " "); '
        "  ty=d; "
        "else "
        '  sz=$(stat -c %s "$f" 2>/dev/null || echo 0); '
        "  cnt=1; ty=f; "
        "fi; "
        'mt=$(stat -c %Y "$f" 2>/dev/null || echo 0); '
        'printf "%s\\t%s\\t%s\\t%s\\t%s\\n" "$ty" "$name" "$sz" "$cnt" "$mt"; '
        "done"
    )
    code, out, err = run_ssh(conn, script, timeout=30)
    if code != 0:
        raise ValueError(f"ラズパイ側の{dir_name}/を確認できませんでした: {err.decode('utf-8', 'replace').strip()}")
    entries = {}
    for line in out.decode("utf-8", "replace").splitlines():
        parts = line.split("\t")
        if len(parts) != 5:
            continue
        ty, name, sz, cnt, mt = parts
        try:
            entries[name] = dict(type=("dir" if ty == "d" else "file"),
                                  size=int(sz), count=int(cnt), mtime=float(mt))
        except ValueError:
            continue
    return entries


def build_directory_audit(conn: dict, local_base: Path, dirs: list) -> dict:
    result = {}
    for dir_name in dirs:
        local_entries = list_local_dir_entries(local_base, dir_name)
        remote_entries = list_remote_dir_entries(conn, conn.get("remote_base_dir", ""), dir_name)
        names = sorted(set(local_entries) | set(remote_entries), key=str.lower)
        rows = []
        for name in names:
            local = local_entries.get(name)
            remote = remote_entries.get(name)
            if local and remote:
                status = "same" if (local["size"] == remote["size"] and local["count"] == remote["count"]) else "differs"
            elif local:
                status = "local_only"
            else:
                status = "remote_only"
            rows.append(dict(name=name, local=local, remote=remote, status=status))
        result[dir_name] = rows
    return result


def validate_audit_target(dirs: list, dir_name: str, entry_name: str) -> None:
    if dir_name not in dirs:
        raise ValueError(f"不明なディレクトリです: {dir_name}")
    if not entry_name or not _SAFE_ENTRY_NAME.fullmatch(entry_name):
        raise ValueError("不正なファイル/フォルダ名です")


def require_rsync() -> str:
    rsync_bin = shutil.which("rsync")
    if not rsync_bin:
        raise ValueError("rsyncコマンドが見つかりません(このMac・ラズパイ双方にrsyncが必要です)")
    return rsync_bin


def rsync_ssh_option(conn: dict) -> str:
    """rsyncの -e オプションに渡す、通常のssh呼び出しと同じ接続オプション文字列。"""
    parts = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8",
             "-o", "StrictHostKeyChecking=accept-new", "-p", str(conn.get("port") or 22)]
    if conn.get("identity_file"):
        parts += ["-i", conn["identity_file"]]
    return " ".join(shlex.quote(p) for p in parts)


def run_rsync(args: list, timeout: int = 300):
    try:
        proc = subprocess.run(args, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise ValueError("転送がタイムアウトしました(データ量が多い場合はターミナルから直接rsync/scpを実行してください)")
    return proc.returncode, proc.stdout, proc.stderr


def audit_pull(conn: dict, local_base: Path, dirs: list, dir_name: str, entry_name: str, is_dir: bool) -> None:
    """ラズパイ側の<dir_name>/<entry_name>をローカルに取り込む(追加・更新のみ。
    ローカルにしか無いファイルの削除は行わない。--deleteを付けない)。"""
    validate_audit_target(dirs, dir_name, entry_name)
    rsync_bin = require_rsync()
    remote_base = conn.get("remote_base_dir") or ""
    if not remote_base:
        raise ValueError("接続設定(ラズパイ上のtogikaidrive-devのパス)を保存してください")
    remote_path = posixpath.join(remote_base, dir_name, entry_name)
    local_path = local_base / dir_name / entry_name
    local_path.parent.mkdir(parents=True, exist_ok=True)
    host_spec = f"{conn.get('user') or 'pi'}@{conn['host']}"
    if is_dir:
        src, dst = f"{host_spec}:{remote_path}/", f"{local_path}/"
    else:
        src, dst = f"{host_spec}:{remote_path}", str(local_path)
    args = [rsync_bin, "-az", "-e", rsync_ssh_option(conn), src, dst]
    code, _out, err = run_rsync(args)
    if code != 0:
        raise ValueError(f"取り込みに失敗しました: {err.decode('utf-8', 'replace').strip()}")


def audit_push(conn: dict, local_base: Path, dirs: list, dir_name: str, entry_name: str, is_dir: bool) -> None:
    """ローカルの<dir_name>/<entry_name>をラズパイに送る(追加・更新のみ)。"""
    validate_audit_target(dirs, dir_name, entry_name)
    rsync_bin = require_rsync()
    remote_base = conn.get("remote_base_dir") or ""
    if not remote_base:
        raise ValueError("接続設定(ラズパイ上のtogikaidrive-devのパス)を保存してください")
    remote_path = posixpath.join(remote_base, dir_name, entry_name)
    local_path = local_base / dir_name / entry_name
    if not local_path.exists():
        raise ValueError(f"ローカルに見つかりません: {local_path}")
    host_spec = f"{conn.get('user') or 'pi'}@{conn['host']}"
    # 送り先の親ディレクトリを先に作っておく(mkdir -p は固定コマンド+安全な引数のみ)
    run_ssh(conn, f"mkdir -p {shlex.quote(posixpath.join(remote_base, dir_name))}")
    if is_dir:
        src, dst = f"{local_path}/", f"{host_spec}:{remote_path}/"
    else:
        src, dst = str(local_path), f"{host_spec}:{remote_path}"
    args = [rsync_bin, "-az", "-e", rsync_ssh_option(conn), src, dst]
    code, _out, err = run_rsync(args)
    if code != 0:
        raise ValueError(f"送信に失敗しました: {err.decode('utf-8', 'replace').strip()}")
