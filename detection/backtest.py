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

