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

