"""Graph-based wash-ring detection for the Stellar DEX.

Single-account detectors (Benford, per-wallet ML features) score wallets in
isolation, so a *ring* of colluding wallets that pass funds around a closed
loop — each individual wallet looking only mildly anomalous — can stay under
the per-wallet threshold while collectively manufacturing large volume.

This module lifts detection from the wallet to the **cluster** level. It
builds the directed trade graph (an edge points from seller to buyer),
partitions it into communities (`greedy_modularity_communities`), and, within
each community, looks for the two structural signatures of self-dealing:

- **Reciprocity** — pairs that trade both ways (A→B *and* B→A). Genuine market
  flow is overwhelmingly one-directional per counterparty over a short window.
- **Circular routing** — directed cycles A→B→C→A that return an asset to its
  origin, the graph analogue of the atomic loops
  `path_payment_engine.detect_atomic_circular_routes` finds within a single tx.

The per-wallet `network_centrality` / `funding_source_similarity` features in
`feature_engineering` describe a wallet's *position* in this graph; this module
produces the complementary artefact — the clusters themselves — surfaced via
`GET /rings`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import networkx as nx
import pandas as pd

# Scoring weights for the composite ring suspicion score (must sum to 100).
_RECIPROCITY_WEIGHT = 40
_CYCLE_WEIGHT = 35
_DENSITY_WEIGHT = 25

# A ring is "cyclic enough" for full cycle credit once it contains this many
# distinct directed cycles; more cycles do not add further suspicion.
_CYCLE_SATURATION = 5

# Hard cap on cycles enumerated per community subgraph so a pathologically
# dense cluster cannot make `simple_cycles` run away.
_MAX_CYCLES_PER_RING = 1000


@dataclass(frozen=True)
class WashRing:
    """A cluster of wallets exhibiting wash-ring structure on one asset pair."""

    ring_id: str
    asset_pair: str
    members: tuple[str, ...]
    size: int
    internal_trade_count: int
    internal_volume: float
    edge_density: float
    reciprocal_edge_ratio: float
    cycle_count: int
    longest_cycle: int
    suspicion_score: int


def ring_id_for(members: list[str], asset_pair: str) -> str:
    """Return a deterministic, order-independent 8-char id for a ring.

    Uses SHA-256[:8] of the sorted members plus asset pair, matching the
    version-hash convention in `detection.model_registry`.
    """
    content = "|".join(sorted(members)) + "::" + asset_pair
    return hashlib.sha256(content.encode()).hexdigest()[:8]


def build_trade_graph(trades: pd.DataFrame) -> nx.DiGraph:
    """Build a directed, weighted wallet trade graph from a `Trade` DataFrame.

    An edge ``seller -> buyer`` is added per trade; the base asset flows from
    seller to buyer. `base_is_seller` decides which side is the seller. Edge
    attributes accumulate across trades:

    - ``weight`` — number of trades along the edge
    - ``volume`` — summed ``base_amount``

    Liquidity-pool trades (``counter_account is None``) and self-trades
    (seller == buyer) are skipped: a pool has no signable wallet, and a
    self-loop carries no ring structure.
    """
    graph = nx.DiGraph()
    if trades is None or trades.empty:
        return graph

    required = {"base_account", "counter_account"}
    if not required.issubset(trades.columns):
        return graph

    base_is_seller = (
        trades["base_is_seller"].astype("boolean").fillna(True).to_numpy()
        if "base_is_seller" in trades.columns
        else pd.Series(True, index=trades.index).to_numpy()
    )
    base = trades["base_account"].to_numpy()
    counter = trades["counter_account"].to_numpy()
    amounts = (
        pd.to_numeric(trades["base_amount"], errors="coerce").fillna(0.0).to_numpy()
        if "base_amount" in trades.columns
        else [0.0] * len(trades)
    )

    for is_bs, b, c, amt in zip(base_is_seller, base, counter, amounts):
        seller, buyer = (b, c) if is_bs else (c, b)
        if seller is None or buyer is None:
            continue
        if pd.isna(seller) or pd.isna(buyer):
            continue
        if seller == buyer:
            continue
        if graph.has_edge(seller, buyer):
            graph[seller][buyer]["weight"] += 1
            graph[seller][buyer]["volume"] += float(amt)
        else:
            graph.add_edge(seller, buyer, weight=1, volume=float(amt))
    return graph


def detect_communities(graph: nx.DiGraph, min_size: int = 2) -> list[set]:
    """Partition `graph` into communities, keeping those with >= `min_size` members.

