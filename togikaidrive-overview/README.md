# togikaidrive-dev 解説スライド

`../../togikaidrive-dev`（外部リポジトリ [autonomous-minicar-battle/togikaidrive-dev](https://github.com/autonomous-minicar-battle/togikaidrive-dev) のクローン）の内容を、プログラムが分からない人にも分かるように解説したスライド資料。

## ファイル

- `togikaidrive_overview.pptx` — 完成したスライド資料（全17枚）
- `build.js` — スライドを生成する pptxgenjs スクリプト（再生成・編集用）

## スライド構成

### 基本編（1〜10）

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

### 高度な機能編（11〜16）

config.py の473設定項目のうち、基本編でカバーしているのは15〜20%程度。残りの本格的なレース競技向け機能を解説。

11. 高度な機能マップ（5ジャンルの概観）
12. 自己位置推定（lidar_slam / slam_toolbox / AMCL / VSLAM / ArUco の比較）
13. 経路追従・最適制御（path_nav → mpc → mppi → mppi_local の段階）
14. YOLOによる物体検知（yolo_detection.py の3つの使い道）
15. ControlArbiter（判断を上書きする安全弁、fallback/events/obstacleの3モード）
16. 強化学習シミュレーター（togikaidrive-sim、f1tenth_gymベースのRL学習パイプライン）

### まとめ

17. まとめ

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
