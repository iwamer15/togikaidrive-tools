# アノテーションツール ランチャー

`togikaidrive-dev/annotation_training_d2j/main.py`(画像アノテーション・学習管理用の既存PyQt5デスクトップアプリ)を、ブラウザから起動するための薄いランチャーツール。

## 背景

`annotation_training_d2j`は29,000行超のPyQt5デスクトップアプリで、画像アノテーション・YOLO/画像ベースモデルの学習・Google Colabへのデータ転送/学習済みモデルの取り込み(Cloudメニュー)までを一通り備えている。しかしWeb機能は一切持たず(`mlflow ui`をサブプロセス起動する以外にHTTPサーバーの仕組みが無い)、`togikaidrive-portal`の他3ツールのように`render_page()`方式でタブ埋め込みすることはできない。

このツールは`main.py`自体を一切変更せず、サブプロセスとして起動するボタンだけを提供する。画像アノテーション・Colab連携などの実際の操作は、起動後のアプリ内で今まで通り行う。

## 使い方

```bash
cd ト技会-minicar/lab/annotation-tool-launcher
python3 server.py
```

ブラウザで `http://localhost:8902` を開く。

## 画面構成

1. **起動** — 「アノテーションツールを起動」ボタン。このサーバーが起動したプロセスが既に動いている場合は再起動せず、その旨を表示する(誤って複数ウィンドウを開かないため)。
2. **セッション情報(参考)** — `annotation_training_d2j/sessions/session.json`があれば最終更新日時などを軽く表示する(形式非依存のベストエフォート表示、無ければ「情報なし」)。

## 制約

- annotation_training_d2j専用の`venv`(`annotation_training_d2j/venv/bin/python3`)があればそれを使って起動し、無ければこのツールを実行しているPythonにフォールバックする。
- プロセスの起動有無はこのサーバー自身が起動したものだけを把握する(サーバーを再起動すると追跡状態はリセットされる)。
- 起動直後(3秒以内)にプロセスが終了した場合は失敗として扱い、ログ(OSの一時フォルダの`togikai-annotation-tool.log`。Macは`/tmp/`、Windowsは`%TEMP%`)の末尾をエラーメッセージに含めて返す。「起動しました」と表示されたのに実際は開いていない、という状態を防ぐため。

## 既知の問題と対処

**macOSで「起動しました」の直後にウィンドウが開かない場合**
venv内のPyQt5がmacOS用の描画プラグイン(cocoa)を自力で見つけられず、`qt.qpa.plugin: Could not find the Qt platform plugin "cocoa"`というエラーで即終了することがある(実際に発生を確認済み)。`shared/app_launcher.py`の`_qt_plugin_env()`が、venv内にバンドルされているプラグインディレクトリ(`venv/lib/python3.*/site-packages/PyQt5/Qt5/plugins/platforms`)を自動検出して`QT_QPA_PLATFORM_PLUGIN_PATH`に設定することで対処済み。それでも起動に失敗する場合は、エラーメッセージに含まれるログの内容を確認すること。
