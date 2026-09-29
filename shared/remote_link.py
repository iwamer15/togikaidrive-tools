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
import io
import json
import posixpath
import re
import shlex
import shutil
import subprocess
import tarfile
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


# ---------------------------------------------------------------------------
# ディレクトリツリー閲覧(任意パス版)
# 上のディレクトリ監査(build_directory_audit等)はAUDIT_DIRSという固定の
# ホワイトリスト(例: ["data", "models"])しか見られない。こちらは同じ安全方針
# (--deleteを付けない、削除は一切しない、ユーザーがボタンを押した時だけ転送)を
# 保ったまま、任意の相対パスを1階層ずつ辿れるようにしたもの。既存のaudit_*系は
# 呼び出し側(config-editorの既存「🔌 ラズパイ連携」監査テーブル)がそのまま動き
# 続けるよう一切変更していない。
# ---------------------------------------------------------------------------
def _split_safe_rel_path(rel_path: str) -> list:
    """相対パスを安全なセグメントのリストに分解する。空文字列は「ルート直下」を表す。
    英数字・._- 以外の文字を含むセグメント、空セグメント、"."/".."セグメントは
    拒否する(パストラバーサル対策。"."と".."は_SAFE_ENTRY_NAMEの文字集合には
    合致してしまうため、ここで名指しして弾く)。"""
    rel_path = (rel_path or "").strip().strip("/")
    if not rel_path:
        return []
    segments = rel_path.split("/")
    for seg in segments:
        if not seg or seg in (".", "..") or not _SAFE_ENTRY_NAME.fullmatch(seg):
            raise ValueError(f"不正なパスです: {rel_path}")
    return segments


def list_local_tree(local_base: Path, rel_path: str) -> list:
    """local_base配下のrel_pathディレクトリの直下一覧を返す。監査版と違い、
    フォルダのサイズは再帰計算せず直下の件数のみ(任意の深い/大きいディレクトリを
    毎回rglobすると遅いため)。"""
    segments = _split_safe_rel_path(rel_path)
    base = local_base.joinpath(*segments) if segments else local_base
    entries = []
    if not base.is_dir():
        return entries
    for child in base.iterdir():
        if child.name.startswith("."):
            continue
        try:
            if child.is_dir():
                count = sum(1 for _ in child.iterdir())
                entries.append(dict(name=child.name, type="dir", size=None, count=count,
                                     mtime=child.stat().st_mtime))
            else:
                st = child.stat()
                entries.append(dict(name=child.name, type="file", size=st.st_size, count=1,
                                     mtime=st.st_mtime))
        except OSError:
            continue  # 権限エラー等はスキップ(一覧全体は止めない)
    entries.sort(key=lambda e: e["name"].lower())
    return entries


def list_remote_tree(conn: dict, remote_base_dir: str, rel_path: str) -> list:
    """list_local_treeのラズパイ版。list_remote_dir_entriesと違い、フォルダの
    サイズは再帰計算せず直下の件数のみを取得する(同じ理由で軽量化のため)。"""
    segments = _split_safe_rel_path(rel_path)
    remote_dir = posixpath.join(remote_base_dir, *segments) if segments else remote_base_dir
    quoted_dir = shlex.quote(remote_dir)
    script = (
        f"[ -d {quoted_dir} ] || exit 0; "
        f"for f in {quoted_dir}/*; do "
        '[ -e "$f" ] || continue; '
        'name=$(basename "$f"); '
        'case "$name" in .*) continue;; esac; '
        'if [ -d "$f" ]; then '
        '  cnt=$(find "$f" -mindepth 1 -maxdepth 1 2>/dev/null | wc -l | tr -d " "); '
        "  ty=d; sz=0; "
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
        label = "/".join(segments) or "(ルート)"
        raise ValueError(f"ラズパイ側の{label}を確認できませんでした: {err.decode('utf-8', 'replace').strip()}")
    entries = []
    for line in out.decode("utf-8", "replace").splitlines():
        parts = line.split("\t")
        if len(parts) != 5:
            continue
        ty, name, sz, cnt, mt = parts
        try:
            is_dir = ty == "d"
            entries.append(dict(name=name, type=("dir" if is_dir else "file"),
                                 size=(None if is_dir else int(sz)), count=int(cnt), mtime=float(mt)))
        except ValueError:
            continue
    entries.sort(key=lambda e: e["name"].lower())
    return entries


def tree_pull(conn: dict, local_base: Path, remote_base_dir: str, rel_path: str, is_dir: bool) -> None:
    """ラズパイ側の<remote_base_dir>/<rel_path>をローカルの<local_base>/<rel_path>に
    取り込む(追加・更新のみ。audit_pullの任意パス版)。"""
    segments = _split_safe_rel_path(rel_path)
    if not segments:
        raise ValueError("転送するファイル/フォルダを指定してください")
    if not remote_base_dir:
        raise ValueError("接続設定(ラズパイ上のtogikaidrive-devのパス)を保存してください")
    rsync_bin = require_rsync()
    remote_path = posixpath.join(remote_base_dir, *segments)
    local_path = local_base.joinpath(*segments)
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


def tree_push(conn: dict, local_base: Path, remote_base_dir: str, rel_path: str, is_dir: bool) -> None:
    """ローカルの<local_base>/<rel_path>をラズパイの<remote_base_dir>/<rel_path>に
    送る(追加・更新のみ。audit_pushの任意パス版)。"""
    segments = _split_safe_rel_path(rel_path)
    if not segments:
        raise ValueError("転送するファイル/フォルダを指定してください")
    if not remote_base_dir:
        raise ValueError("接続設定(ラズパイ上のtogikaidrive-devのパス)を保存してください")
    rsync_bin = require_rsync()
    remote_path = posixpath.join(remote_base_dir, *segments)
    local_path = local_base.joinpath(*segments)
    if not local_path.exists():
        raise ValueError(f"ローカルに見つかりません: {local_path}")
    host_spec = f"{conn.get('user') or 'pi'}@{conn['host']}"
    remote_parent = posixpath.dirname(remote_path)
    run_ssh(conn, f"mkdir -p {shlex.quote(remote_parent)}")
    if is_dir:
        src, dst = f"{local_path}/", f"{host_spec}:{remote_path}/"
    else:
        src, dst = str(local_path), f"{host_spec}:{remote_path}"
    args = [rsync_bin, "-az", "-e", rsync_ssh_option(conn), src, dst]
    code, _out, err = run_rsync(args)
    if code != 0:
        raise ValueError(f"送信に失敗しました: {err.decode('utf-8', 'replace').strip()}")


# ---------------------------------------------------------------------------
# ツール一式のラズパイへの配置(rsync不要版)と、ラズパイ上の常駐プロセス管理
# 上のaudit_*/tree_*はrsyncを使う(macOS/Linux前提)。こちらはWindowsのメンバーでも
# 使えるよう、Python標準のtarfileで固めたバイト列をsshの標準入力に流して
# ラズパイ側の`tar -xf -`で展開する(ssh以外のコマンドに依存しない)。
# ---------------------------------------------------------------------------
_DEPLOY_ALWAYS_EXCLUDE = {"__pycache__", ".DS_Store"}


def push_directories_tar(conn: dict, local_root: Path, names: list, remote_parent: str,
                         exclude_names=()) -> int:
    """local_root直下のnames(ディレクトリ名のリスト)を、ラズパイのremote_parent直下に
    上書き展開する(追加・更新のみ。ラズパイ側にしか無いファイルは消さない)。
    exclude_namesに含まれる名前(パスのどの階層でも)と`__pycache__`/`.pyc`は送らない。
    送ったファイル数を返す。namesは呼び出し側が固定で渡す前提で、安全な名前のみ許可する。"""
    if not remote_parent:
        raise ValueError("ラズパイ上の配置先が決まっていません(接続設定を確認してください)")
    excluded = set(exclude_names) | _DEPLOY_ALWAYS_EXCLUDE
    buf = io.BytesIO()
    count = 0
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as tar:
        for name in names:
            if not _SAFE_ENTRY_NAME.fullmatch(name) or name in (".", ".."):
                raise ValueError(f"不正な名前です: {name}")
            base = local_root / name
            if not base.is_dir():
                raise ValueError(f"ローカルに見つかりません: {base}")
            for path in sorted(base.rglob("*")):
                rel = path.relative_to(local_root)
                if any(part in excluded or part.endswith(".pyc") for part in rel.parts):
                    continue
                if not path.is_file() or path.is_symlink():
                    continue
                info = tar.gettarinfo(str(path), arcname=rel.as_posix())
                info.uid = info.gid = 0
                info.uname = info.gname = ""
                with path.open("rb") as f:
                    tar.addfile(info, f)
                count += 1
    quoted = shlex.quote(remote_parent)
    code, _out, err = run_ssh(conn, f"mkdir -p {quoted} && tar -xf - -C {quoted}",
                              input_bytes=buf.getvalue(), timeout=120)
    if code != 0:
        raise ValueError(f"ラズパイへの配置に失敗しました: {err.decode('utf-8', 'replace').strip()}")
    return count


def _daemon_files(name: str) -> tuple:
    if not _SAFE_ENTRY_NAME.fullmatch(name):
        raise ValueError(f"不正な名前です: {name}")
    return f"/tmp/togikai-{name}.pid", f"/tmp/togikai-{name}.log"


def remote_daemon_start(conn: dict, name: str, workdir: str, command: str,
                        python_exe: str = "") -> dict:
    """ラズパイ上でcommandをバックグラウンド起動する(sshを切っても動き続ける)。
    commandは呼び出し側が固定で組み立てた文字列のみを渡すこと(自由入力を渡さない)。
    commandの中では`"$PY"`でpython_exe(無ければpython3)を参照できる。
    PIDは/tmp/togikai-<name>.pid、標準出力/エラーは/tmp/togikai-<name>.logに残す。
    既に同名のプロセスが動いていれば新しくは起動しない。"""
    pidf, logf = _daemon_files(name)
    inner = shlex.quote(f"echo $$ > {pidf}; exec {command}")
    script = (
        f'if [ -f {pidf} ] && kill -0 "$(cat {pidf})" 2>/dev/null; then echo "ALREADY:$(cat {pidf})"; exit 0; fi; '
        f"cd {shlex.quote(workdir)} || {{ echo NOWORKDIR; exit 3; }}; "
        f"PY={shlex.quote(python_exe)}; [ -n \"$PY\" ] && [ -x \"$PY\" ] || PY=python3; export PY; "
        f"rm -f {pidf}; "
        f"setsid nohup sh -c {inner} > {logf} 2>&1 < /dev/null & "
        f"i=0; while [ ! -s {pidf} ] && [ $i -lt 30 ]; do sleep 0.1; i=$((i+1)); done; "
        f'echo "STARTED:$(cat {pidf} 2>/dev/null)"'
    )
    code, out, err = run_ssh(conn, script, timeout=30)
    text = out.decode("utf-8", "replace").strip()
    if "NOWORKDIR" in text:
        raise ValueError(f"ラズパイ上に{workdir}がありません。先に「ツールを配置/更新」を実行してください")
    if code != 0:
        raise ValueError(f"起動に失敗しました: {err.decode('utf-8', 'replace').strip() or text}")
    kind, _, pid = text.splitlines()[-1].partition(":")
    return dict(already=(kind == "ALREADY"), pid=(int(pid) if pid.isdigit() else None))


def remote_daemon_status(conn: dict, name: str, port: int | None = None, log_lines: int = 25) -> dict:
    """{running, pid, listening, log}を返す。listeningはportが指定された時だけ意味を持つ。"""
    pidf, logf = _daemon_files(name)
    port_check = ""
    if port is not None:
        port_check = f'(ss -ltn 2>/dev/null | grep -q ":{int(port)} ") && echo LISTEN:1 || echo LISTEN:0; '
    script = (
        f'if [ -f {pidf} ]; then pid=$(cat {pidf}); '
        f'if kill -0 "$pid" 2>/dev/null; then echo "STATE:RUNNING:$pid"; else echo STATE:DEAD; fi; '
        f"else echo STATE:NONE; fi; "
        f"{port_check}"
        f"echo ---LOG---; tail -n {int(log_lines)} {logf} 2>/dev/null; exit 0"
    )
    code, out, err = run_ssh(conn, script, timeout=20)
    if code != 0:
        raise ValueError(f"状態の取得に失敗しました: {err.decode('utf-8', 'replace').strip()}")
    head, _, log = out.decode("utf-8", "replace").partition("---LOG---\n")
    running, pid, listening = False, None, False
    for line in head.splitlines():
        if line.startswith("STATE:RUNNING:"):
            running = True
            pid_text = line.split(":", 2)[2]
            pid = int(pid_text) if pid_text.isdigit() else None
        elif line == "LISTEN:1":
            listening = True
    return dict(running=running, pid=pid, listening=listening, log=log)


def remote_daemon_stop(conn: dict, name: str, match: str) -> str:
    """remote_daemon_startで起動したプロセスにSIGTERMを送り、最大6秒待っても終わらなければ
    SIGKILLする。PID再利用による誤停止を避けるため、cmdlineにmatch(固定文字列)を含む
    ことを確認してから送る。戻り値: STOPPED / KILLED / NONE / NOTRUNNING / MISMATCH。"""
    pidf, _logf = _daemon_files(name)
    if not re.fullmatch(r"[A-Za-z0-9_.\-]+", match or ""):
        raise ValueError("不正な照合文字列です")
    script = (
        f"[ -f {pidf} ] || {{ echo NONE; exit 0; }}; "
        f"pid=$(cat {pidf}); "
        f'if ! kill -0 "$pid" 2>/dev/null; then rm -f {pidf}; echo NOTRUNNING; exit 0; fi; '
        f"if ! tr '\\0' ' ' < /proc/$pid/cmdline | grep -q -- {shlex.quote(match)}; then rm -f {pidf}; echo MISMATCH; exit 0; fi; "
        f'kill -TERM "$pid"; i=0; '
        f'while kill -0 "$pid" 2>/dev/null && [ $i -lt 30 ]; do sleep 0.2; i=$((i+1)); done; '
        f'if kill -0 "$pid" 2>/dev/null; then kill -KILL "$pid"; echo KILLED; else echo STOPPED; fi; '
        f"rm -f {pidf}"
    )
    code, out, err = run_ssh(conn, script, timeout=30)
    if code != 0:
        raise ValueError(f"停止に失敗しました: {err.decode('utf-8', 'replace').strip()}")
    return out.decode("utf-8", "replace").strip().splitlines()[-1]
