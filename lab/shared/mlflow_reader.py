"""
togikaidrive-tools 共通: MLflow(mlruns/)のファイル直接読み取り
====================================================================
`annotation_training_d2j`はMLflowのローカルファイルストア(`mlruns/`)に
画像学習の実験記録を残す(Colabで学習→Google Driveからダウンロード→
ローカルにマージ、という流れは`annotation_training_d2j/main.py`側で完結済み)。

本モジュールは`mlflow`パッケージを使わず、そのファイル形式を直接読むだけの
薄い読み取り専用ヘルパー。ポータル側に`mlflow`パッケージを追加インストールせずに
学習分析パネルでメトリクスを表示するために存在する(3ツールが守ってきた
「追加pipライブラリなし」という方針を維持するため)。

前提にしているファイル形式(実際のmlruns/を確認して合わせてある):
    mlruns/<experiment_id>/meta.yaml
    mlruns/<experiment_id>/<run_id>/meta.yaml
    mlruns/<experiment_id>/<run_id>/params/<name>       (1行、値そのもの)
    mlruns/<experiment_id>/<run_id>/tags/<name>         (1行、値そのもの)
    mlruns/<experiment_id>/<run_id>/metrics/<name>      (複数行、
                                                          "<timestamp_ms> <value> <step>")
meta.yamlはネストの無い"key: value"の並びのみを前提にする(実データで確認済み)。
"""
from __future__ import annotations

from pathlib import Path

from . import env_check

HERE = Path(__file__).resolve().parent
TOOLS_ROOT = HERE.parent  # lab/
REPO_ROOT = TOOLS_ROOT.parent  # ト技会-minicar/ (togikaidrive-dev/ がある場所)
DEFAULT_MLRUNS_DIR = (
    env_check.resolve_togikaidrive_dev(REPO_ROOT) / "annotation_training_d2j" / "mlruns"
)

_SKIP_EXPERIMENT_DIRS = {".trash"}


def _parse_simple_yaml(path: Path) -> dict:
    """ネストの無い"key: value"の並びだけを前提にした最小限のYAML風パーサー。
    値がシングルクォート/ダブルクォートで囲まれていれば剥がす。壊れた行は無視する。"""
    result: dict = {}
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return result
    for line in text.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        result[key] = value
    return result


def _read_text_file(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except Exception:
        return None


def list_experiments(mlruns_dir: Path = DEFAULT_MLRUNS_DIR) -> list[dict]:
    """mlruns_dir直下の実験一覧を返す(名前・ID)。mlruns_dirが無ければ空リスト。"""
    if not mlruns_dir.exists():
        return []
    experiments = []
    for entry in sorted(mlruns_dir.iterdir()):
        if not entry.is_dir() or entry.name in _SKIP_EXPERIMENT_DIRS:
            continue
        meta = _parse_simple_yaml(entry / "meta.yaml")
        if not meta:
            continue
        experiments.append(dict(
            experiment_id=meta.get("experiment_id", entry.name),
            name=meta.get("name", entry.name),
            path=str(entry),
        ))
    return experiments


def list_runs(experiment_dir: Path) -> list[dict]:
    """1つの実験ディレクトリ配下のrun一覧を、開始時刻の新しい順に返す。"""
    if not experiment_dir.exists():
        return []
    runs = []
    for entry in sorted(experiment_dir.iterdir()):
        if not entry.is_dir():
            continue
        meta = _parse_simple_yaml(entry / "meta.yaml")
        if not meta:
            continue
        run_name = meta.get("run_name") or _read_text_file(entry / "tags" / "mlflow.runName") or entry.name
        status = _read_text_file(entry / "tags" / "status") or meta.get("status", "-")
        runs.append(dict(
            run_id=meta.get("run_id", entry.name),
            run_name=run_name,
            status=status,
            start_time=_to_int(meta.get("start_time")),
            end_time=_to_int(meta.get("end_time")),
            path=str(entry),
        ))
    runs.sort(key=lambda r: r["start_time"] or 0, reverse=True)
    return runs


def _to_int(value) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def list_params(run_dir: Path) -> dict:
    params_dir = Path(run_dir) / "params"
    if not params_dir.exists():
        return {}
    result = {}
    for entry in sorted(params_dir.iterdir()):
        if entry.is_file():
            value = _read_text_file(entry)
            if value is not None:
                result[entry.name] = value
    return result


def list_metric_names(run_dir: Path) -> list[str]:
    metrics_dir = Path(run_dir) / "metrics"
    if not metrics_dir.exists():
        return []
    return sorted(p.name for p in metrics_dir.iterdir() if p.is_file())


def read_metric_history(run_dir: Path, metric_name: str) -> list[dict]:
    """`(step, timestamp_ms, value)`のリストを、ファイルに書かれた順(通常はstep順)で返す。
    行の形式は "<timestamp_ms> <value> <step>"。壊れた行は読み飛ばす。"""
    metric_path = Path(run_dir) / "metrics" / metric_name
    if not metric_path.exists():
        return []
    points = []
    try:
        lines = metric_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    for line in lines:
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            timestamp = int(parts[0])
            value = float(parts[1])
            step = int(parts[2]) if len(parts) > 2 else 0
        except ValueError:
            continue
        points.append(dict(step=step, timestamp=timestamp, value=value))
    return points
