"""Tests for the real-time streaming scorer (`detection.streaming`)."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from detection import streaming
from detection.streaming import InMemoryStreamSource, StreamWorker
from ingestion.data_models import Asset, Trade

NATIVE = Asset(code="XLM", issuer=None)
USDC = Asset(code="USDC", issuer="GA5ZSEJYB37JRC5AVCIA5MOP4RHTM335X2KGX3IHOJAPP5RE34K4KZVN")


class _HighRiskModel:
    """Stub classifier that always predicts a high wash probability."""

    def predict_proba(self, X):
        n = len(X)
        return np.array([[0.05, 0.95]] * n)


def _make_trade(trade_id: int, base: str, counter: str, amount: float, when: datetime) -> Trade:
    return Trade(
        id=str(trade_id),
        ledger_close_time=when,
        base_account=base,
        counter_account=counter,
        base_asset=NATIVE,
        counter_asset=USDC,
        base_amount=amount,
        counter_amount=amount * 0.1,
        price=0.1,
        base_is_seller=trade_id % 2 == 0,
    )


@pytest.fixture
def high_risk_models():
    # Keys must match ensemble weight names in score_feature_vector.
    return {"random_forest": _HighRiskModel(), "xgboost": _HighRiskModel(), "lightgbm": _HighRiskModel()}


# ---------------------------------------------------------------------------
# High-score trade enqueues a webhook alert
# ---------------------------------------------------------------------------


def test_high_score_trade_enqueues_webhook(high_risk_models, monkeypatch):
    # Arrange: stub out the registry/queue side of the enqueue path.
    class _Sub:
        subscriber_id = "sub-1"

    enqueued = []
    monkeypatch.setattr("detection.webhook_registry.init_db", lambda *a, **k: None)
    monkeypatch.setattr("detection.webhook_registry.get_matching_subscribers", lambda score, db_path=None: [_Sub()])
    monkeypatch.setattr("detection.webhook_queue.init_db", lambda *a, **k: None)
    monkeypatch.setattr(
        "detection.webhook_queue.enqueue",
        lambda subscriber_id, payload, db_path=None: enqueued.append((subscriber_id, payload)),
    )

    worker = StreamWorker(
        InMemoryStreamSource(),
        models=high_risk_models,
        score_threshold=50,
        persist_scores=False,
    )
    now = datetime.now(timezone.utc)
    trade = _make_trade(1, "GAAA", "GBBB", 1000.0, now)

    # Act
    produced = worker.process_trade(trade)

    # Assert
    assert all(s.score >= 50 for s in produced)
    assert len(enqueued) >= 1
    assert enqueued[0][0] == "sub-1"


# ---------------------------------------------------------------------------
# Scores update as new trades arrive
# ---------------------------------------------------------------------------


def test_scores_update_as_trades_arrive(high_risk_models):
    # Arrange
    worker = StreamWorker(
        InMemoryStreamSource(),
        models=high_risk_models,
        score_threshold=101,  # never alert; isolate the scoring behaviour
        persist_scores=False,
        enqueue_alerts=False,
    )
    now = datetime.now(timezone.utc)

    # Act: two trades for the same wallet/pair.
    worker.process_trade(_make_trade(1, "GAAA", "GBBB", 1000.0, now))
    first = worker.latest_scores[("GAAA", "XLM/USDC")]
    worker.process_trade(_make_trade(2, "GAAA", "GCCC", 2000.0, now + timedelta(seconds=30)))
    second = worker.latest_scores[("GAAA", "XLM/USDC")]

    # Assert: buffer grew and the latest score is a fresh record.
    assert worker._buffers[worker._buffer_key("GAAA", "XLM/USDC")].maxlen == 500
    assert len(worker._buffers[worker._buffer_key("GAAA", "XLM/USDC")]) == 2
    assert second is not first


# ---------------------------------------------------------------------------
# Clean shutdown
# ---------------------------------------------------------------------------


def test_run_drains_finite_source_and_stops(high_risk_models):
    # Arrange
    source = InMemoryStreamSource()
    now = datetime.now(timezone.utc)
    for i in range(3):
        source.publish(_make_trade(i, "GAAA", "GBBB", 100.0 * (i + 1), now + timedelta(seconds=i)))
    source.close()

    worker = StreamWorker(source, models=high_risk_models, score_threshold=101, persist_scores=False, enqueue_alerts=False)

    # Act
    processed = worker.run()

    # Assert
    assert processed == 3


def test_stop_halts_before_max_trades(high_risk_models):
    # Arrange: an unbounded (never-closed) source.
    source = InMemoryStreamSource()
    now = datetime.now(timezone.utc)
    for i in range(5):
        source.publish(_make_trade(i, "GAAA", "GBBB", 100.0, now + timedelta(seconds=i)))

    worker = StreamWorker(source, models=high_risk_models, score_threshold=101, persist_scores=False, enqueue_alerts=False)

    # Act: max_trades bounds the loop even though the source stays open.
    processed = worker.run(max_trades=2)

    # Assert
    assert processed == 2


def test_publish_after_close_raises():
    # Arrange
    source = InMemoryStreamSource()
    source.close()

    # Act / Assert
    with pytest.raises(RuntimeError):
        source.publish(_make_trade(1, "GAAA", "GBBB", 100.0, datetime.now(timezone.utc)))
