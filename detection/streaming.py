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

