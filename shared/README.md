# shared/(3ツール共通モジュール)

`togikaidrive-config-editor`・`data-preprocessing-tool`・`training-execution-tool`の3つが共通で使う、**ツール固有のドメイン知識を持たない**モジュール置き場。3ツールは今後もそれぞれ独立したポート/プロセスの`http.server`ベースのローカルツールとして動くが、見た目やラズパイ連携のような横断的な機能は重複実装せずここに集約する。

pipライブラリは増やさない(標準ライブラリのみ)。各ツールは起動時に`sys.path.insert(0, <ト技会-minicar/>)`してから`from shared import ui_kit, remote_link`のようにimportする。

## ui_kit.py

- `PALETTE` / `ACCENT_COLOR` / `ACCENT_TINT`: 色定義。
- `html_escape(text)`: HTMLエスケープ。
- `BASE_CSS`: `:root`の色変数 + body/header/card/toastなど、3ツールでほぼ同一だった基礎スタイル。
- `COMMON_JS`: `showToast(msg, isError)` / `escapeHtml(s)`(3ツールで文言まで同一だったもの)。

## remote_link.py

SSHでラズパイに接続し、ファイル/ディレクトリをこのMacと相互に反映するための共通処理。

- **接続設定**: `load_connection()` / `save_connection(data)`。`shared/ssh_connection.json`(`.gitignore`済み、環境固有)に保存する。ホスト名・ユーザー名・ポート・SSH秘密鍵パス・ラズパイ上の`togikaidrive-dev`ディレクトリの絶対パス(`remote_base_dir`)を持つ。パスワード認証はサポートしない。
- **SSH基礎**: `run_ssh(conn, remote_command, ...)` / `test_connection(conn)`。`remote_command`は呼び出し側が固定で組み立てた文字列のみを渡す前提(自由入力のコマンド実行はどのツールにも実装しない)。
- **単一テキストファイルの相互反映**(config.pyのような「1ファイル丸ごと」向け): `fetch_remote_text` / `diff_text` / `push_text_file` / `pull_text_file`。push/pullは書き換え前に必ずバックアップを作る。
- **ディレクトリ監査**(data/models のような大量ファイル・大容量フォルダ向け): `build_directory_audit(conn, local_base, dirs)`でローカル/ラズパイの差分を読み取り専用で一覧化し、`audit_pull` / `audit_push`でフォルダ/ファイル単位に転送する(`rsync -az`、`--delete`なしで削除は一切発生しない)。`dirs`は呼び出し側の固定リストのみを受け付ける。

## 使う側の例(togikaidrive-config-editorから抜粋)

```python
TOOLS_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(TOOLS_ROOT))
from shared import remote_link, ui_kit

PALETTE = ui_kit.PALETTE
_html_escape = ui_kit.html_escape

def diff_local_remote() -> dict:
    conn = remote_link.load_connection()
    remote_text = remote_link.fetch_remote_text(conn, remote_config_path(conn))
    local_text = CONFIG_PATH.read_text(encoding="utf-8")
    return remote_link.diff_text(local_text, remote_text)
```

`config.py`のようなツール固有のパス組み立て(`remote_base_dir` + `"config.py"`など)は各ツール側の薄いラッパー関数が担当し、`remote_link.py`自身はconfig.py/catalog/学習モデルなどの存在を一切知らない。
