# モーター校正パネル

`togikaidrive-dev/motor.py` のステアリング/スロットルPWM校正を、ターミナルの対話式ウィザードではなく**ブラウザ上**で行い、確定した値をそのまま `config.py` に書き込むためのローカルツール。

## 背景

`motor.py` の `adjust_steering()` / `adjust_throttle()` は、値を入力→実機が動く→Enterで確定、を繰り返す対話式ウィザードだが、**結果をターミナルに表示するだけ**で `config.py` への書き込みは手作業でコピペする必要がある。このツールは、同じ校正操作をブラウザから行いつつ、確定した値を [togikaidrive-config-editor](../togikaidrive-config-editor) と同じ安全な書き込み処理でそのまま `config.py` に反映することでこの手作業をなくす。

`motor.py` 自体は外部ベースプログラムのため**一切変更しない**。既存の `Motor` クラスの公開インターフェース(`set_steering_pwm_value` / `set_throttle_pwm_value` / `limit_steering_pwm` / `cleanup`、および `self.pwm` / `self.CHANNEL_STEERING` / `self.CHANNEL_THROTTLE`)をそのまま利用している。

## 使い方

```bash
cd ト技会-minicar/motor-calibration-panel
python3 server.py
```

ブラウザで `http://localhost:8900` を開く。

## 画面構成

1. **ライブテスト** — ステアリング/スロットルそれぞれ -1〜1 のスライダー。動かすたびに現在の `config.py` の値で実際にどう動くかを試せる。常時表示の「■ 停止」ボタンで即座に中立へ戻せる。
2. **ステアリング校正** — 生のPWM値を入力して「送信(テスト)」で実機を動かし(`motor.py` のウィザードと同じ操作感)、良い値が見つかったら「これを中央にする」/「これを左右どちらかの最大にする」で確定する。最大値を確定すると `STEERING_WIDTH_PWM = |値 - 中央|` が自動計算される。
3. **スロットル校正** — 同様に生PWM値をテスト送信し、「これを停止(ニュートラル)にする」「これを前進最大にする」「これを後退最大にする」でそれぞれ個別に確定する(このconfig.pyでは3値は対称ではなく独立した実測値のため)。
4. **確定した値** — 5項目(`STEERING_CENTER_PWM` / `STEERING_WIDTH_PWM` / `THROTTLE_STOPPED_PWM` / `THROTTLE_FORWARD_PWM` / `THROTTLE_REVERSE_PWM`)の現在値→新しい値を一覧表示。「config.pyに保存」を押すまではファイルには一切書き込まれない。

`STEERING_RIGHT_PWM` / `STEERING_LEFT_PWM` は `config.py` 内で `STEERING_CENTER_PWM ± STEERING_WIDTH_PWM` の計算式になっているため、この2項目だけを書き込めば自動的に追従する。

## 実機接続 / モックモードの自動判定

起動時に `Adafruit_PCA9685` と実機の `Motor()` の初期化を試み、失敗した場合は自動的に同じ公開インターフェースを持つモック(ログ出力のみ)にフォールバックする。画面上部のバッジで常にどちらの状態かを表示するため、誤って「動いていると思ったら実は送信されていなかった」ということはない。

- 🟢 実機接続中 — 実際にPCA9685へPWM信号を送信し、サーボ/ESCが物理的に動く
- ⚪ モック(シミュレーション)モード — `Adafruit_PCA9685` が無い環境(開発機など)向けのダミー動作。ログにのみ出力し、実機は一切動かない

## 安全性

- **標準ライブラリのみ**で動作(pip install不要)
- ページを開いただけでは何も送信しない。スライダー操作・送信ボタン・ロックボタンを押した時だけ実機に指令を送る
- 生PWM値のテスト送信は100〜600の範囲でサーバー側バリデーション
- `motor.py` のウィザードと同じ注意書き(「ジジッとノイズが鳴り続ける場合は壊れる兆候」)を常時表示
- `config.py` への書き込みは [togikaidrive-config-editor](../togikaidrive-config-editor) と同じ仕組みを再利用: 保存のたびに `config.py.bak.<日時>` の自動バックアップを作成してから、**実際に値が変わった行だけ**を正規表現で書き換える(触っていない項目・コメント・空白は一切変化しない)
- 万が一おかしくなったら、直前のバックアップファイルを `config.py` にコピーし直せば元に戻る

```bash
# 元に戻す例
cp ../togikaidrive-dev/config.py.bak.20260906_235143 ../togikaidrive-dev/config.py
```

## 制約

- 実際にPCA9685へ信号を送るには実機(ラズパイ/Jetson)上でI2Cバスと `Adafruit_PCA9685` ライブラリが必要。開発機で動かした場合は自動でモックモードになり、UI・校正ロジック・`config.py` への書き込みまでは確認できるが、**実際にサーボ/ESCが動くことはこのツール単体では確認できない**。実機での動作確認は必ずラズパイ/Jetson上で行うこと。

## 今後の予定

実機での動作確認が済み次第、このパネルを [togikaidrive-config-editor](../togikaidrive-config-editor) の「操作」カテゴリに埋め込み、1つのツールとして統合する予定。
