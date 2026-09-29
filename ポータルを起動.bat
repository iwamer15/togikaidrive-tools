@echo off
REM togikaidrive ポータルをダブルクリックで起動するためのスクリプト(Windows用)。
REM 1. このファイルと同じ場所にある togikaidrive-portal\server.py を起動する
REM 2. サーバーが立ち上がるのを少し待ってからブラウザを自動で開く
REM 終了するにはこのウィンドウで Ctrl+C を押すか、ウィンドウを閉じる。

cd /d "%~dp0togikaidrive-portal"
if not exist server.py (
  echo エラー: togikaidrive-portal フォルダが見つかりません。
  echo このファイルを ト技会-minicar フォルダの直下に置いたまま実行してください。
  pause
  exit /b 1
)

echo togikaidrive ポータルを起動しています...
start "" /b cmd /c "timeout /t 2 /nobreak >nul & start http://localhost:8898"

where python >nul 2>nul
if %errorlevel%==0 (
  python server.py
  goto :done
)
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 server.py
  goto :done
)
where python3 >nul 2>nul
if %errorlevel%==0 (
  python3 server.py
  goto :done
)

echo エラー: Pythonが見つかりません。Python 3 をインストールしてから、もう一度実行してください。
echo (インストール時に「Add python.exe to PATH」にチェックを入れてください)

:done
echo.
pause
