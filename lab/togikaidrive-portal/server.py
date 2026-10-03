#!/usr/bin/env python3
"""
togikaidrive ポータル
======================
設定エディタ(togikaidrive-config-editor)・前処理ツール(data-preprocessing-tool)・
学習実行ツール(training-execution-tool)・画像学習パネル(image-learning-tool)・
アノテーションツールランチャー(annotation-tool-launcher)を、1ポート/1プロセスで
横断的に使えるようにするローカルツール。

パネル構成(トップレベルタブ):
    - 設定(config-editor) — この中に「🧠 機械学習」「📸 画像学習」が
      サブタブとして埋め込まれる(training-execution-tool / image-learning-tool の
      本文をconfig-editor自身のタブバーに追加注入する。詳細はrender_portal_page()を参照)。
    - データ前処理(data-preprocessing-tool)
    - ラズパイ実機(raspi-control-tool) — ラズパイ上の設定エディタ(実機のモーター校正等)を、
      ツール配置・起動・停止までボタンで行う。ポータル自身はMac/Windowsで動くため
      モーターは「モック」であり、実機に触れる操作はラズパイ上のプロセスが担う。
    - アノテーションツール(annotation-tool-launcher) — 既存のPyQt5デスクトップアプリ
      (annotation_training_d2j)を起動するボタンのみ。中身は書き直さない。

設計方針:
    - 各ツールのコード自体は(HTTPルーティングの薄いリファクタを除き)変更しない。
      各ツールは今まで通りそれぞれ単体でも起動できる(`python3 server.py`)。
      ポータルはそれに加わる追加の起動方法という位置づけ。
    - 各ツールの`render_page()`(スタンドアロン用フルページ)から、
      `shared/ui_kit.py`の`extract_panel()`でヘッダー・トースト要素・<main>タグを
      取り除いた「本文」だけを取り出し、1ページの中にタブパネルとして同居させる。
      各パネルのCSSは`scope_css()`でパネルごとにスコープ化し(各ツールとも
      `:root`/`body`/`header`/`main`を独自に再定義していたため、素朴に連結すると
      カスケードで衝突する)、パネル間で衝突しないようにしている。
    - training-execution-tool・image-learning-toolは「トップレベルタブ」としては
      表示せず、config-editorの`render_page(extra_tabs=...)`引数経由でconfig-editor
      自身のタブバーに追加注入する(ユーザー要望のパネルツリー: 設定パネルの下に
      機械学習/画像学習パネルを置く構成に合わせるため)。ただし`handle_get`/
      `handle_post`によるHTTPルーティングは他ツールと同様に`TOOLS`に含めて振り分ける。
    - HTTPルーティング(`/save`・`/api/records`・`/train/start`等)は各ツールの間で
      パス名が重複していないことを確認済みのため、各ツールの`handle_get`/
      `handle_post`関数を順番に試すだけで正しく振り分けられる。
    - 追加のpipライブラリは使わない。

使い方:
    python3 server.py
    → ブラウザで http://localhost:8898 を開く
"""
from __future__ import annotations

import importlib.util
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8898
HERE = Path(__file__).resolve().parent
TOOLS_ROOT = HERE.parent  # lab/ (兄弟ツールとshared/がある場所)
REPO_ROOT = TOOLS_ROOT.parent  # ト技会-minicar/ (togikaidrive-dev/ がある場所)

sys.path.insert(0, str(TOOLS_ROOT))
from shared import ui_kit  # noqa: E402
from shared.http_kit import JSONHandlerMixin  # noqa: E402


def _load_tool(module_name: str, dir_name: str):
    """兄弟ツールのserver.pyを読み込む。3ツールとも同名(server.py)なので、
    素朴に`import server`すると sys.modules["server"] のキャッシュ衝突で
    2つ目以降が1つ目のモジュールを指してしまう。それぞれ一意な名前で
    sys.modulesに登録することで回避する(training-execution-toolが自分の
    兄弟ツールを読み込む際に使っている手法と同じ)。"""
    path = TOOLS_ROOT / dir_name / "server.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


config_editor = _load_tool("togikaidrive_portal_config_editor", "togikaidrive-config-editor")
data_tool = _load_tool("togikaidrive_portal_data_preprocessing", "data-preprocessing-tool")
training_tool = _load_tool("togikaidrive_portal_training_execution", "training-execution-tool")
image_learning_tool = _load_tool("togikaidrive_portal_image_learning", "image-learning-tool")
annotation_launcher_tool = _load_tool("togikaidrive_portal_annotation_launcher", "annotation-tool-launcher")
raspi_tool = _load_tool("togikaidrive_portal_raspi_control", "raspi-control-tool")

# HTTPルーティング(handle_get/handle_post)の振り分け対象。トップレベルタブとして
# 表示するかどうか(PORTAL_TABS)とは独立している(training_tool/image_learning_toolは
# config-editorに埋め込まれるだけでルーティングは自分自身で持つため、ここには残す)。
TOOLS = [config_editor, data_tool, training_tool, image_learning_tool, annotation_launcher_tool, raspi_tool]

# ポータルのトップレベルタブ順(この順でタブが並ぶ)。training_tool/image_learning_toolは
# ここに含めない(config_editorのタブバーに注入されるため)。
PORTAL_TABS = [config_editor, data_tool, raspi_tool, annotation_launcher_tool]

# 各ツールのスタンドアロン起動時のmain()相当の初期化(モーター・判断ロジック・
# YOLO検知の実機/ライブラリ有無チェック)。データ前処理・学習実行ツールは
# モジュールを読み込むだけで使える(main()側は`ThreadingHTTPServer`の起動のみ)。
config_editor.TEMPLATES_DIR.mkdir(exist_ok=True)
config_editor.get_snapshot(force=True)
config_editor.init_motor()
config_editor.init_planner()
config_editor.init_yolo()


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------
PORTAL_CSS = '''
  header { background: var(--navy); color: #fff; padding: 1.4rem 1.5rem; }
  header .eyebrow { color: var(--cyan); font-size: 0.75rem; font-weight: 700; letter-spacing: 0.12em; }
  header h1 { margin: 0.3rem 0 0.4rem; font-size: 1.4rem; }
  header p { margin: 0; color: #B9C0D4; font-size: 0.8rem; }
  .portal-tabs-nav {
    position: sticky; top: 0; z-index: 20; background: #fff; border-bottom: 1px solid #E4E7F0;
    display: flex; overflow-x: auto; padding: 0 0.6rem;
  }
  .portal-tab-btn {
    border: none; background: none; padding: 0.9rem 1.1rem; font-size: 0.9rem; font-weight: 700;
    color: var(--muted); cursor: pointer; white-space: nowrap; border-bottom: 3px solid transparent;
  }
  .portal-tab-btn.active { color: var(--text-dark); border-bottom-color: var(--orange); }
  .portal-tab-panel { display: none; }
  .portal-tab-panel.active { display: block; }
'''

PORTAL_JS = '''
function portalSwitchTab(id) {
  document.querySelectorAll('.portal-tab-btn').forEach(b => b.classList.toggle('active', b.dataset.portalTab === id));
  document.querySelectorAll('.portal-tab-panel').forEach(p => p.classList.toggle('active', p.id === 'portal-panel-' + id));
}
'''


def _config_editor_extra_tabs() -> list[dict]:
    """config-editorのタブバーに追加注入する「🧠 機械学習」「📸 画像学習」パネルを組み立てる。
    training_tool/image_learning_toolの`render_page()`(スタンドアロン用フルページ)から
    本文/CSSを抜き出し、機械学習パネルにはconfig-editor自身が持つ学習結果表示
    (`render_training_results_widget()`、従来「判断」タブに埋め込まれていたもの)を
    合わせて渡す(config-editor側で二重表示にならないよう、render_page()には
    `hide_ml_results_in_decision=True`を渡して「判断」タブ側の表示を止めてもらう)。"""
    ml_body, ml_css = ui_kit.extract_panel(training_tool.render_page())
    il_body, il_css = ui_kit.extract_panel(image_learning_tool.render_page())
    return [
        # アイコン/タイトルはtraining_tool自身のPANEL_ICON/PANEL_TITLE("🚀 学習実行"、
        # スタンドアロン起動時のタブ名)ではなく、ユーザー要望のパネルツリーに合わせて
        # ここで「🧠 機械学習」に読み替える(実行+学習分析を1つにまとめたタブのため)。
        dict(
            id="ml_train", icon="🧠", title="機械学習",
            body_html=ml_body, css=ml_css,
            extra_body_html=config_editor.render_training_results_widget(),
        ),
        dict(
            id="image_learning", icon=image_learning_tool.PANEL_ICON, title=image_learning_tool.PANEL_TITLE,
            body_html=il_body, css=il_css, extra_body_html="",
        ),
    ]


def render_portal_page() -> str:
    tabs_nav = ""
    panels = ""
    style_blocks = [ui_kit.BASE_CSS, PORTAL_CSS]
    script_blocks = [ui_kit.COMMON_JS, PORTAL_JS]

    for i, tool in enumerate(PORTAL_TABS):
        active = "active" if i == 0 else ""
        tabs_nav += (
            f'<button class="portal-tab-btn {active}" data-portal-tab="{tool.PANEL_ID}" '
            f'onclick="portalSwitchTab(\'{tool.PANEL_ID}\')">{tool.PANEL_ICON} {tool.PANEL_TITLE}</button>'
        )
        if tool is config_editor:
            full_html = config_editor.render_page(
                extra_tabs=_config_editor_extra_tabs(), hide_ml_results_in_decision=True,
            )
        else:
            full_html = tool.render_page()
        body, css = ui_kit.extract_panel(full_html)
        style_blocks.append(ui_kit.scope_css(css, f"#portal-panel-{tool.PANEL_ID}"))
        panels += f'<section class="portal-tab-panel {active}" id="portal-panel-{tool.PANEL_ID}">{body}</section>\n'

    return f'''<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>togikaidrive ポータル</title>
<style>
{"".join(style_blocks)}
</style>
</head>
<body>
<header>
  <div class="eyebrow">TOGIKAIDRIVE · PORTAL</div>
  <h1>togikaidrive ポータル</h1>
  <p>設定エディタ・走行データ前処理・学習実行を1つの画面で行き来できます。</p>
</header>
<div id="toast"></div>
<nav class="portal-tabs-nav">{tabs_nav}</nav>
{panels}
<script>
{"".join(script_blocks)}
</script>
</body>
</html>'''


# ---------------------------------------------------------------------------
# サーバー
# 各ツールのhandle_get/handle_postは、それぞれが自分のパス(/save, /api/records,
# /train/start等)以外ならFalseを返す設計になっている。3ツールの間でパスが
# 重複していないことを確認済みなので、単純に順番に試すだけで正しく振り分けられる。
# ---------------------------------------------------------------------------
class Handler(JSONHandlerMixin, BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._send_html(render_portal_page())
            return
        if self.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        for tool in TOOLS:
            if tool.handle_get(self, self.path):
                return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        try:
            posted = self._read_json_body()
            for tool in TOOLS:
                if tool.handle_post(self, self.path, posted):
                    return
            self.send_response(404)
            self.end_headers()
        except ValueError as e:
            self._send_json(400, dict(ok=False, message=str(e)))
        except Exception as e:  # noqa: BLE001
            self._send_json(500, dict(ok=False, message=f"予期しないエラー: {e}"))


def local_ip() -> str:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def main():
    with ThreadingHTTPServer(("0.0.0.0", PORT), Handler) as httpd:
        print("=" * 60)
        print("togikaidrive ポータル を起動しました")
        print(f"  モーター:      {'実機接続' if config_editor.HARDWARE_AVAILABLE else 'モック(シミュレーション)'}")
        print(f"  判断ロジック:  {'利用可能' if config_editor.PLANNER_AVAILABLE else '利用不可(依存ライブラリ不足)'}")
        print(f"  YOLO検知:      {'利用可能' if config_editor.YOLO_AVAILABLE else '利用不可(依存ライブラリ不足)'}")
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
                config_editor.motor_instance.cleanup()
            except Exception:  # noqa: BLE001
                pass


if __name__ == "__main__":
    main()
