"""
togikaidrive-tools 共通UI部品
==============================
設定エディタ・前処理ツール・学習実行ツールの3つが、それぞれ独立したポート/プロセスの
`http.server`ベースのローカルツールでありながら見た目を揃えられるよう、色パレット・
HTMLエスケープ・繰り返し書かれていたJS(トースト通知・HTMLエスケープ)をここに集約する。

このモジュール自身は「どのツールなのか」を一切知らない(config.py/catalog/train_pytorch.py
などのドメイン知識を持たない)。各ツールのserver.pyが、このモジュールの値を使って
自分のページを組み立てる。
"""
from __future__ import annotations

import html
import re

# ---------------------------------------------------------------------------
# 色パレット(元はtogikaidrive-config-editorのPALETTEをそのまま移設)
# ---------------------------------------------------------------------------
PALETTE = dict(
    navy="#10131A", steel="#1F2A44", steel_soft="#3A4A6B", cyan="#00B4C6",
    orange="#FF4B2B", white="#FFFFFF", card_bg="#F3F5FA", text_dark="#16192A",
    muted="#6B7280", orange_tint="#FFEDE9", cyan_tint="#E4FAFC", steel_tint="#EAEEF6",
)

ACCENT_COLOR = {"cyan": PALETTE["cyan"], "orange": PALETTE["orange"], "steel": PALETTE["steel"]}
ACCENT_TINT = {"cyan": PALETTE["cyan_tint"], "orange": PALETTE["orange_tint"], "steel": PALETTE["steel_tint"]}


def html_escape(text) -> str:
    return html.escape(str(text), quote=True)


# ---------------------------------------------------------------------------
# 共通CSS: `:root`の色変数 + body/header/card/toastなど、3ツールでほぼ同一だった
# 基礎スタイルだけを抜き出したもの。各ツールはこれをstyleブロックの先頭に埋め込み、
# 自分固有のスタイルはその後ろに追記する(上書きしたい場合は同じセレクタを後ろに
# 書けばCSSの優先順位でそちらが勝つ)。
# ---------------------------------------------------------------------------
BASE_CSS = f'''
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
  header {{ background: var(--navy); color: #fff; padding: 1.4rem 1.5rem; }}
  header .eyebrow {{ color: var(--cyan); font-size: 0.75rem; font-weight: 700; letter-spacing: 0.12em; }}
  header h1 {{ margin: 0.3rem 0 0.4rem; font-size: 1.4rem; }}
  header p {{ margin: 0; color: #B9C0D4; font-size: 0.8rem; }}
  .card {{ background: #fff; border-radius: 16px; box-shadow: 0 8px 24px rgba(16,19,26,0.08); padding: 1.2rem 1.4rem; }}
  .card h2 {{ margin: 0 0 0.6rem; font-size: 1.05rem; }}
  .card .sub {{ margin: 0 0 1rem; color: var(--muted); font-size: 0.82rem; }}
  #toast {{
    position: fixed; top: 1rem; left: 50%; transform: translateX(-50%) translateY(-140%);
    background: var(--navy); color: #fff; padding: 0.7rem 1.2rem; border-radius: 10px;
    font-size: 0.85rem; transition: transform 0.25s ease; z-index: 10; max-width: 90vw;
  }}
  #toast.show {{ transform: translateX(-50%) translateY(0); }}
  #toast.error {{ background: var(--orange); }}
'''

# ---------------------------------------------------------------------------
# 共通JS: トースト通知とHTMLエスケープ(3ツールで文言まで同一だったもの)。
# 各ツールの<script>ブロックの先頭にそのまま埋め込む。
# ---------------------------------------------------------------------------
COMMON_JS = '''
function showToast(msg, isError) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = isError ? 'show error' : 'show';
  setTimeout(() => { t.className = ''; }, 3200);
}

function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = String(s);
  return div.innerHTML;
}
'''

# ---------------------------------------------------------------------------
# ポータル用: 各ツールのCSSをパネル単位にスコープ化する
# 3ツールはそれぞれ独立ページとして`:root`/`*`/`body`/`header`/`main`など同じ
# セレクタを再定義しているため、1ページに同居させるとカスケードで衝突する。
# 各ツールのCSSは「フラットな `セレクタ[, セレクタ2...] { プロパティ }` の並び」
# (@media等のネストなし)という前提で、各ルールを子孫セレクタとしてプレフィックス
# を付け直す。この前提は3ツールとも実際に成り立っている(手書きCSSで@media未使用)。
# ---------------------------------------------------------------------------
_DROP_SELECTOR_HEADS = {"body", "html"}


def scope_css(css: str, prefix: str, main_class: str = "tool-main") -> str:
    """`css`の各ルールに`prefix`(子孫結合子)を付けてスコープ化した文字列を返す。

    - `:root` / `*` / `body` / `html` / `header` を含むルールは丸ごと捨てる
      (共通シェル側のBASE_CSSが1回だけ定義するため)。
    - `#toast` を含むルールも丸ごと捨てる(BASE_CSSが既に定義済みで、ポータルでは
      パネル間で共有する1つのトースト要素を使うため)。
    - 裸の`main`要素セレクタは`.{main_class}`に読み替える(1ページに複数の
      <main>を置かないよう、パネル抽出時に<main>を<div class="...">へ
      置き換えることとセットで使う)。
    """
    out_rules = []
    for chunk in css.split("}"):
        chunk = chunk.strip()
        if not chunk or "{" not in chunk:
            continue
        selector_part, _, props = chunk.partition("{")
        selectors = [s.strip() for s in selector_part.split(",") if s.strip()]
        kept = []
        for sel in selectors:
            if sel in (":root", "*") or sel.startswith("#toast"):
                continue
            first_word = sel.split(" ", 1)[0]
            bare = first_word.split(":", 1)[0].split(".", 1)[0].split("#", 1)[0].split("[", 1)[0]
            if bare in _DROP_SELECTOR_HEADS:
                continue
            if bare == "main":
                sel = f".{main_class}" + sel[len(first_word):]
            kept.append(f"{prefix} {sel}")
        if not kept:
            continue
        out_rules.append(f"{', '.join(kept)} {{{props}}}")
    return "\n".join(out_rules)


def extract_panel(full_html: str) -> tuple[str, str]:
    """スタンドアロンページの完成HTML(各ツールの`render_page()`の戻り値)から、
    ポータルに埋め込める(本文HTML, CSSテキスト)を取り出す。

    3ツールとも「<style>1個・<div id="toast"></div>1個・<main>1個」という
    一貫した構造で書かれているという前提(実際に成り立っている)。
    - CSSは<style>の中身をそのまま返す(呼び出し側でscope_css()に通すこと)。
    - 本文は<body>の中身から<div id="toast"></div>を除いたもの。<header>は
      あえて残す(設定エディタの<header>には再読み込み/テンプレートボタンなど
      機能を持つ要素が入っており、一律で消すと機能ごと失われるため。見た目上は
      各パネルが自分の見出しを持つ形になる。1ページに複数の<div id="toast">を
      置かないための除去だけを行う)。
    - <main>はポータル1ページに複数の<main>を置かないよう<div class="tool-main">に
      読み替える(scope_css()の main_class 引数と対応させること)。
    """
    css_match = re.search(r"<style>(.*?)</style>", full_html, re.S)
    css = css_match.group(1) if css_match else ""

    body_match = re.search(r"<body>(.*?)</body>", full_html, re.S)
    body = body_match.group(1) if body_match else full_html

    body = re.sub(r'<div id="toast"></div>', "", body)
    body = body.replace("<main>", '<div class="tool-main">').replace("</main>", "</div>")
    return body, css
