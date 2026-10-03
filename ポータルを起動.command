#!/bin/bash
# togikaidrive ポータルをダブルクリックで起動するためのスクリプト(Mac用)。
# 1. このファイルと同じ場所にある lab/togikaidrive-portal/server.py を起動する
# 2. サーバーが立ち上がるのを少し待ってからブラウザを自動で開く
# 終了するにはこのターミナルのウィンドウで Ctrl+C を押すか、ウィンドウを閉じる。
cd "$(dirname "$0")/lab/togikaidrive-portal" || {
  echo "エラー: lab/togikaidrive-portal フォルダが見つかりません。"
  echo "このファイルを ト技会-minicar フォルダの直下に置いたまま実行してください。"
  read -r -p "Enterキーで閉じます..."
  exit 1
}

if ! command -v python3 >/dev/null 2>&1; then
  echo "エラー: python3 が見つかりません。Python 3 をインストールしてから、もう一度実行してください。"
  read -r -p "Enterキーで閉じます..."
  exit 1
fi

echo "togikaidrive ポータルを起動しています..."
( sleep 1.5 && open "http://localhost:8898" ) &

python3 server.py
echo
read -r -p "終了しました。Enterキーで閉じます..."
