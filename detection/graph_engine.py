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


