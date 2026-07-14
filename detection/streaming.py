"""Real-time / streaming risk scoring.

The batch pipeline (`run_pipeline.run`) scores a whole historical window at
once. This module scores trades *as they arrive*: a `StreamWorker` consumes
`Trade` objects from a pluggable `StreamSource`, buffers them per
``(wallet, asset_pair)``, re-scores the affected wallets incrementally, and
enqueues webhook alerts (via `detection.webhook_queue` +
`detection.webhook_registry`) within seconds — the same delivery path used by
`run_pipeline._enqueue_webhook_alerts`.

Transport is pluggable behind the `StreamSource` protocol:

- `InMemoryStreamSource` — an in-process queue, used by tests and for
  embedding the worker in another process.
- `CallableStreamSource` — adapts any iterable / generator function (e.g. a
  Kafka or Redis consumer) without this module depending on that backend.
- `HorizonStreamSource` — wraps `ingestion.horizon_streamer.stream_trades`.

No streaming backend (Kafka/Redis/etc.) is a hard dependency: the default
in-memory and Horizon sources rely only on stdlib plus what is already in
``requirements.txt``. Additional backends plug in as `CallableStreamSource`
adapters.
"""

import logging
import queue
import threading
from collections import deque
from collections.abc import Iterable, Iterator
from typing import Protocol, runtime_checkable

import pandas as pd

from config.settings import settings
from detection.feature_engineering import build_feature_vector
from detection.model_inference import load_models, score_feature_vector
from detection.risk_score import RiskScore
from ingestion.data_models import Trade

logger = logging.getLogger("hedge-rod.streaming")

DEFAULT_BUFFER_SIZE = 500


# ---------------------------------------------------------------------------
# Stream sources
# ---------------------------------------------------------------------------


@runtime_checkable
class StreamSource(Protocol):
    """A source of `Trade` objects the worker can iterate over.

    Iteration blocks until the next trade is available and stops (raises
    `StopIteration`) when the source is exhausted or closed.
    """

    def __iter__(self) -> Iterator[Trade]: ...


class InMemoryStreamSource:
    """An in-process, thread-safe `StreamSource` backed by a queue.

    Producers call `publish` (and `close` when done); the worker iterates.
    Iteration ends after `close` once the backlog is drained, giving tests a
    clean, deterministic shutdown.
    """

    _SENTINEL = object()

    def __init__(self, trades: Iterable[Trade] | None = None) -> None:
        self._queue: queue.Queue = queue.Queue()
        self._closed = False
        for trade in trades or []:
            self._queue.put(trade)

    def publish(self, trade: Trade) -> None:
        if self._closed:
            raise RuntimeError("Cannot publish to a closed StreamSource")
        self._queue.put(trade)

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._queue.put(self._SENTINEL)

    def __iter__(self) -> Iterator[Trade]:
        while True:
            item = self._queue.get()
            if item is self._SENTINEL:
                return
            yield item


class CallableStreamSource:
    """Adapt any iterable or zero-arg generator function into a `StreamSource`.

    This is the extension point for external transports (Kafka, Redis
    Streams, etc.): wrap the consumer's generator here instead of adding a
    hard dependency on the backend to this module.
    """

    def __init__(self, factory: Iterable[Trade] | "callable") -> None:
        self._factory = factory

    def __iter__(self) -> Iterator[Trade]:
        source = self._factory() if callable(self._factory) else self._factory
        yield from source


class HorizonStreamSource:
    """`StreamSource` backed by the live Horizon SSE trade stream."""

    def __init__(self, cursor: str = "now") -> None:
        self._cursor = cursor

    def __iter__(self) -> Iterator[Trade]:
        from ingestion.horizon_streamer import stream_trades

        yield from stream_trades(cursor=self._cursor)


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


def _involved_accounts(trade: Trade) -> list[str]:
    """Return the wallet accounts to (re)score for `trade`.

    Pool trades have no counterparty wallet (`counter_account is None`), so
    only the base account is scored for those.
    """
    accounts = [trade.base_account]
    if trade.counter_account is not None:
        accounts.append(trade.counter_account)
    return [a for a in accounts if a]


class StreamWorker:
    """Consume trades from a `StreamSource` and score wallets incrementally.

    Per ``(wallet, asset_pair)`` a bounded buffer of recent trades is kept;
    each incoming trade re-scores its involved wallets over that buffer and,
    when a score meets the alert threshold, enqueues webhook alerts to
    matching subscribers.
    """

    def __init__(
        self,
        source: StreamSource,
        models: dict | None = None,
        buffer_size: int = DEFAULT_BUFFER_SIZE,
        score_threshold: int | None = None,
        db_path: str | None = None,
        enqueue_alerts: bool = True,
        persist_scores: bool = True,
    ) -> None:
        self._source = source
        self._models = models
        self._buffer_size = buffer_size
        self._threshold = score_threshold if score_threshold is not None else settings.risk_score_threshold
        self._db_path = db_path
        self._enqueue_alerts = enqueue_alerts
        self._persist_scores = persist_scores

        self._buffers: dict[str, deque[Trade]] = {}
        self.latest_scores: dict[tuple[str, str], RiskScore] = {}
        self._stop_event = threading.Event()

    # -- model access -------------------------------------------------------

    def _get_models(self) -> dict:
        if self._models is None:
            self._models = load_models()
        return self._models

    # -- buffering ----------------------------------------------------------

    def _buffer_key(self, account: str, asset_pair: str) -> str:
        return f"{account}\x1f{asset_pair}"

    def _append(self, account: str, asset_pair: str, trade: Trade) -> deque[Trade]:
        key = self._buffer_key(account, asset_pair)
        buffer = self._buffers.get(key)
        if buffer is None:
            buffer = deque(maxlen=self._buffer_size)
            self._buffers[key] = buffer
        buffer.append(trade)
        return buffer

    # -- scoring ------------------------------------------------------------

    def _score_account(self, account: str, asset_pair: str, buffer: deque[Trade]) -> RiskScore:
        trades_df = pd.DataFrame([t.model_dump() for t in buffer])
        trades_df["ledger_close_time"] = pd.to_datetime(trades_df["ledger_close_time"], utc=True)
        as_of = pd.Timestamp(trades_df["ledger_close_time"].max())

        features = build_feature_vector(trades_df, account, as_of)
        probability, confidence = score_feature_vector(self._get_models(), features)

        return RiskScore.combine(
            wallet=account,
            asset_pair=asset_pair,
            benford_mad=features.get("benford_mad_24h", 0.0),
            benford_mad_threshold=settings.benford_mad_threshold,
            ml_probability=probability,
            ml_confidence=confidence,
        )

    def process_trade(self, trade: Trade) -> list[RiskScore]:
        """Buffer `trade` and return an updated `RiskScore` per involved wallet.

        Side effects (persistence, webhook enqueue) run for scores at or
        above the alert threshold.
        """
        asset_pair = trade.asset_pair
        produced: list[RiskScore] = []

        for account in _involved_accounts(trade):
            buffer = self._append(account, asset_pair, trade)
            score = self._score_account(account, asset_pair, buffer)
            self.latest_scores[(account, asset_pair)] = score
            produced.append(score)

        alerts = [s for s in produced if s.score >= self._threshold]
        if alerts:
            if self._persist_scores:
                self._persist(alerts)
            if self._enqueue_alerts:
                self._enqueue(alerts)

        return produced

    # -- side effects -------------------------------------------------------

    def _persist(self, scores: list[RiskScore]) -> None:
        try:
            from detection.storage import save_scores

            save_scores(scores, db_path=self._db_path)
        except Exception:
            logger.exception("Failed to persist streamed scores")

    def _enqueue(self, scores: list[RiskScore]) -> None:
        try:
            from detection.webhook_queue import enqueue, init_db as init_queue
            from detection.webhook_registry import get_matching_subscribers, init_db as init_registry

            init_registry(self._db_path)
            init_queue(self._db_path)
            for score in scores:
                for sub in get_matching_subscribers(score, db_path=self._db_path):
                    enqueue(sub.subscriber_id, score.model_dump(), db_path=self._db_path)
        except Exception:
            logger.exception("Failed to enqueue webhook alerts for streamed scores")

    # -- lifecycle ----------------------------------------------------------

    def stop(self) -> None:
        """Signal the consumer loop to stop after the current trade."""
        self._stop_event.set()

    def run(self, max_trades: int | None = None) -> int:
        """Consume trades from the source until it ends, `stop()`, or `max_trades`.

        Returns the number of trades processed. Errors scoring an individual
        trade are logged and skipped so one bad trade cannot kill the loop.
        """
        processed = 0
        logger.info(
            "Stream worker started (threshold=%d, buffer_size=%d)",
            self._threshold,
            self._buffer_size,
        )
        for trade in self._source:
            if self._stop_event.is_set():
                break
            try:
                self.process_trade(trade)
            except Exception:
                logger.exception("Failed to process streamed trade id=%s", getattr(trade, "id", "?"))
            processed += 1
            if max_trades is not None and processed >= max_trades:
                break

        logger.info("Stream worker stopped after %d trade(s)", processed)
        return processed
