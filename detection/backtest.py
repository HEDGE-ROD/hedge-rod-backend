"""Backtesting / labeled-evaluation harness for the HedgeRod ensemble.

Ingests a *frozen* historical trade window plus a labelled ground-truth set
of known wash cases, scores every wallet with the trained ensemble via the
same scoring path used in `run_pipeline.run`, and produces a classification
report (precision / recall / F1 / AUC-ROC / PR-AUC / confusion matrix) at a
configurable score threshold.

Two dataset sources are supported (see `load_frozen_dataset`):

- the synthetic labelled generator in `ingestion.synthetic_data`, and
- a directory / file pair of ingested trades plus a CSV or JSON of
  ``{wallet, asset_pair, is_wash}`` labels.

Reports are written as JSON to ``./backtest_reports/YYYYMMDD_HHMM.json``,
mirroring the drift-report pattern in `cli.retrain_check`.
"""

import ast
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from config.settings import settings
from detection.feature_engineering import build_feature_vector
from detection.model_inference import load_models, score_feature_matrix
from detection.risk_score import RiskScore

logger = logging.getLogger("hedge-rod.backtest")

DEFAULT_REPORT_DIR = "./backtest_reports"
DEFAULT_ASSET_PAIR = "XLM/USDC"

# Column aliases accepted for the binary wash label in external files.
_LABEL_COLUMNS = ("is_wash", "label", "wash", "y")


@dataclass(frozen=True)
class FrozenDataset:
    """A frozen trade window plus per-wallet ground-truth labels.

    `labels` maps a wallet id to ``1`` (known wash) or ``0`` (known clean).
    `trades` is a `Trade`-shaped DataFrame as produced by
    `ingestion.synthetic_data.generate_synthetic_dataset` or by reloading a
    persisted trades CSV/JSON.
    """

    trades: pd.DataFrame
    labels: dict[str, int]
    account_metadata: dict[str, dict] = field(default_factory=dict)
    order_book_events: pd.DataFrame | None = None
    asset_pair: str = DEFAULT_ASSET_PAIR


@dataclass(frozen=True)
class BacktestScoring:
    """Aligned scoring output: one entry per labelled wallet."""

    wallets: list[str]
    y_true: list[int]
    y_scores: list[int]
    scores: list[RiskScore]


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------


def from_synthetic(
    n_normal_accounts: int = 60,
    n_wash_rings: int = 10,
    ring_size: int = 3,
    seed: int = 42,
    asset_pair: str = DEFAULT_ASSET_PAIR,
) -> FrozenDataset:
    """Build a `FrozenDataset` from the synthetic labelled generator."""
    from ingestion.synthetic_data import generate_synthetic_dataset

    trades, account_metadata, events, labels = generate_synthetic_dataset(
        n_normal_accounts=n_normal_accounts,
        n_wash_rings=n_wash_rings,
        ring_size=ring_size,
        seed=seed,
    )
    return FrozenDataset(
        trades=trades,
        labels={w: int(v) for w, v in labels.items()},
        account_metadata=account_metadata,
        order_book_events=events,
        asset_pair=asset_pair,
    )


def _literal_eval_asset_columns(trades: pd.DataFrame) -> pd.DataFrame:
    """Parse `base_asset`/`counter_asset` string reprs back into dicts.

    CSV round-trips serialise the nested `Asset` dicts as Python-literal
    strings; the feature engineering layer needs them as real dicts.
    """
    trades = trades.copy()
    for col in ("base_asset", "counter_asset"):
        if col in trades.columns and trades[col].dtype == object:
            trades[col] = trades[col].map(
                lambda v: ast.literal_eval(v) if isinstance(v, str) and v.startswith("{") else v
            )
    return trades


def _read_trades_file(path: str) -> pd.DataFrame:
    """Load a trades CSV or JSON into a `Trade`-shaped DataFrame."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Trades file not found: {path}")
    if path.endswith(".json"):
        trades = pd.read_json(path)
    else:
        trades = pd.read_csv(path)
    if trades.empty:
        return trades
    trades = _literal_eval_asset_columns(trades)
    trades["ledger_close_time"] = pd.to_datetime(trades["ledger_close_time"], utc=True)
    return trades.sort_values("ledger_close_time").reset_index(drop=True)


def _extract_label(record: dict) -> int | None:
    for col in _LABEL_COLUMNS:
        if col in record and record[col] is not None and not pd.isna(record[col]):
            return int(bool(int(float(record[col]))))
    return None


def read_labels_file(path: str) -> dict[str, int]:
    """Read a labels CSV or JSON of ``{wallet, asset_pair, is_wash}`` rows.

    Accepts several column aliases for the binary label
    (``is_wash``/``label``/``wash``/``y``). Returns ``{wallet: 0|1}``; if a
    wallet appears more than once the last labelled row wins.
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Labels file not found: {path}")

    if path.endswith(".json"):
        with open(path) as f:
            payload = json.load(f)
        records = payload if isinstance(payload, list) else payload.get("labels", [])
    else:
        records = pd.read_csv(path).to_dict("records")

    labels: dict[str, int] = {}
    for record in records:
        wallet = record.get("wallet")
        if not wallet:
            continue
        label = _extract_label(record)
        if label is not None:
            labels[str(wallet)] = label
    if not labels:
        raise ValueError(f"No usable labels parsed from {path}")
    return labels


def from_files(
    trades_path: str,
    labels_path: str,
    order_book_events_path: str | None = None,
    account_metadata: dict[str, dict] | None = None,
    asset_pair: str = DEFAULT_ASSET_PAIR,
) -> FrozenDataset:
    """Build a `FrozenDataset` from persisted trades + a labels file."""
    trades = _read_trades_file(trades_path)
    labels = read_labels_file(labels_path)

