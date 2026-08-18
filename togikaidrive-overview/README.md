# togikaidrive-dev 解説スライド

`../../togikaidrive-dev`（外部リポジトリ [autonomous-minicar-battle/togikaidrive-dev](https://github.com/autonomous-minicar-battle/togikaidrive-dev) のクローン）の内容を、プログラムが分からない人にも分かるように解説したスライド資料。

## ファイル

- `togikaidrive_overview.pptx` — 完成したスライド資料（全11枚）
- `build.js` — スライドを生成する pptxgenjs スクリプト（再生成・編集用）

## スライド構成

1. タイトル
2. 全体像（1枚で分かる認知→判断→操作の3ステップ）
3. プログラム構成マップ（run.py を中心とした各プログラムの役割）
4. 実行フロー（run.py起動→メインループ→学習ループの、プログラム間の実際の呼び出し順序）
5. run.py（メインループ）
6. config.py（設定ファイル）
7. 認知（ultrasonic.py / camera.py / lidar.py）
8. planner.py（判断ロジック）
9. motor.py（PWM変換）
10. train_pytorch.py + data_viewer（学習の流れ）
11. まとめ

## 再生成・編集する場合

```bash
cd docs/togikaidrive-overview
npm install
node build.js
# → togikaidrive_overview.pptx が上書き生成される
```

内容を変更したい場合は `build.js` 内の各スライドのテキスト・図解部分を編集してから再実行する。

## 注意

`togikaidrive-dev/` は外部組織のリポジトリをクローンしたものなので、このスライド資料や関連ファイルは `docs/togikaidrive-overview/`（このリポジトリ側）に置き、`togikaidrive-dev/` 配下には手を加えない方針。
