"""Tests for detection.graph_engine (wash-ring detection)."""

import pandas as pd
import pytest

from detection.graph_engine import (
    WashRing,
    build_trade_graph,
    detect_communities,
    detect_wash_rings,
    find_trade_cycles,
    ring_id_for,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _trade_row(
    seller: str,
    buyer: str,
    amount: float = 100.0,
    base_is_seller: bool = True,
    counter_account: str | None = None,
    time: pd.Timestamp | None = None,
) -> dict:
    """One trade row shaped like `Trade.model_dump()`.

    If `base_is_seller`, base_account is the seller. `counter_account`
    overrides the buyer/None (used for pool trades).
    """
    base = seller if base_is_seller else buyer
    counter = counter_account if counter_account is not None else (buyer if base_is_seller else seller)
    return {
        "ledger_close_time": time or pd.Timestamp.now(tz="UTC"),
        "base_account": base,
        "counter_account": counter,
        "base_amount": amount,
        "base_is_seller": base_is_seller,
    }


def _ring_trades(members: list[str], reps: int = 3) -> pd.DataFrame:
    """Dense circular ring: each member sells to the next, repeated `reps`x,
    plus reciprocal edges back. This is the wash-ring signature.
    """
    rows: list[dict] = []
    n = len(members)
    for _ in range(reps):
        for i, seller in enumerate(members):
            buyer = members[(i + 1) % n]
            rows.append(_trade_row(seller, buyer))
            rows.append(_trade_row(buyer, seller))  # reciprocal
    return pd.DataFrame(rows)


def _sparse_trades(n_wallets: int = 20) -> pd.DataFrame:
    """Legitimate-looking market: a directional chain of distinct wallets with
    no reciprocal edges and no cycles — the opposite of a wash ring.
    """
    rows = [_trade_row(f"L{i}", f"L{i + 1}") for i in range(n_wallets - 1)]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# build_trade_graph
# ---------------------------------------------------------------------------


def test_build_trade_graph_nodes_and_edges():
    trades = pd.DataFrame([_trade_row("A", "B"), _trade_row("B", "C")])
    g = build_trade_graph(trades)
    assert set(g.nodes) == {"A", "B", "C"}
    assert g.has_edge("A", "B")
    assert g.has_edge("B", "C")


def test_build_trade_graph_directed_seller_to_buyer():
    # base_is_seller=True => base_account (A) sells to counter (B): edge A->B
    trades = pd.DataFrame([_trade_row("A", "B", base_is_seller=True)])
    g = build_trade_graph(trades)
    assert g.has_edge("A", "B")
    assert not g.has_edge("B", "A")


def test_build_trade_graph_edge_weight_accumulates():
    trades = pd.DataFrame([_trade_row("A", "B", amount=10.0)] * 3)
    g = build_trade_graph(trades)
    assert g["A"]["B"]["weight"] == 3
    assert g["A"]["B"]["volume"] == pytest.approx(30.0)


def test_build_trade_graph_skips_pool_trades():
    # Pool trades carry counter_account=None and must not create a phantom node.
    trades = pd.DataFrame([_trade_row("A", "B", counter_account=None)])
    # force counter to None explicitly
    trades.loc[0, "counter_account"] = None
    g = build_trade_graph(trades)
    assert None not in g.nodes


def test_build_trade_graph_empty():
    g = build_trade_graph(pd.DataFrame())
    assert g.number_of_nodes() == 0


# ---------------------------------------------------------------------------
# detect_communities
# ---------------------------------------------------------------------------


def test_detect_communities_finds_dense_cluster():
    trades = _ring_trades(["A", "B", "C"])
    g = build_trade_graph(trades)
    communities = detect_communities(g, min_size=3)
    assert any({"A", "B", "C"}.issubset(c) for c in communities)


def test_detect_communities_respects_min_size():
    trades = pd.DataFrame([_trade_row("A", "B")])
    g = build_trade_graph(trades)
    communities = detect_communities(g, min_size=3)
    assert communities == []

