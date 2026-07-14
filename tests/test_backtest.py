"""Tests for the backtesting / labeled-evaluation harness."""

import json

import joblib
import numpy as np
import pytest
from sklearn.ensemble import RandomForestClassifier

from detection import backtest
from detection.backtest import (
    BacktestScoring,
    FrozenDataset,
    build_report,
    compute_classification_report,
    from_synthetic,
    read_labels_file,
    run_backtest,
    score_dataset,
    threshold_sweep,
    write_report,
)
from detection.feature_engineering import FEATURE_NAMES


# ---------------------------------------------------------------------------
# Metric computation
# ---------------------------------------------------------------------------


def test_perfect_separation_scores_all_metrics_one():
    # Arrange: labels perfectly separated by the threshold.
    y_true = [1, 1, 0, 0]
    y_scores = [90, 80, 10, 20]

    # Act
    report = compute_classification_report(y_true, y_scores, threshold=50)

    # Assert
    assert report["precision"] == 1.0
    assert report["recall"] == 1.0
    assert report["f1"] == 1.0
    assert report["auc_roc"] == 1.0
    assert report["confusion_matrix"] == {"tp": 2, "fp": 0, "tn": 2, "fn": 0}
    assert report["support"] == {"positives": 2, "negatives": 2, "total": 4}


def test_confusion_matrix_counts_false_positives_and_negatives():
    # Arrange: one FP (clean scored high) and one FN (wash scored low).
    y_true = [1, 1, 0, 0]
    y_scores = [90, 40, 80, 10]

    # Act
    report = compute_classification_report(y_true, y_scores, threshold=50)

    # Assert
    cm = report["confusion_matrix"]
    assert cm == {"tp": 1, "fp": 1, "tn": 1, "fn": 1}
    assert report["precision"] == pytest.approx(0.5)
    assert report["recall"] == pytest.approx(0.5)


def test_single_class_labels_yield_none_auc():
    # Arrange: only negatives -> ranking metrics undefined.
    y_true = [0, 0, 0]
    y_scores = [10, 20, 30]

    # Act
    report = compute_classification_report(y_true, y_scores, threshold=50)

    # Assert
    assert report["auc_roc"] is None
    assert report["pr_auc"] is None
    assert report["precision"] == 0.0  # no positive predictions -> 0/0 guarded


def test_threshold_sweep_covers_all_thresholds():
    # Arrange
    y_true = [1, 0, 1, 0]
    y_scores = [70, 30, 90, 10]

    # Act
    sweep = threshold_sweep(y_true, y_scores, thresholds=[20, 50, 80])

    # Assert
    assert [r["threshold"] for r in sweep] == [20, 50, 80]
    # Higher thresholds never increase recall.
    recalls = [r["recall"] for r in sweep]
    assert recalls == sorted(recalls, reverse=True)


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------


def test_score_dataset_empty_labels_returns_empty_scoring():
    # Arrange
    empty = FrozenDataset(trades=from_synthetic(n_normal_accounts=2, n_wash_rings=1, ring_size=2).trades, labels={})

    # Act
    scoring = score_dataset(empty, models={})

    # Assert
    assert scoring.wallets == []
    assert scoring.y_true == []
    assert scoring.y_scores == []


def test_compute_report_handles_empty_lists():
    # Act
    report = compute_classification_report([], [], threshold=50)

    # Assert
    assert report["support"]["total"] == 0
    assert report["f1"] == 0.0
    assert report["auc_roc"] is None

