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


# ---------------------------------------------------------------------------
# find_trade_cycles
# ---------------------------------------------------------------------------


def test_find_trade_cycles_detects_three_cycle():
    trades = pd.DataFrame(
        [
            _trade_row("A", "B"),
            _trade_row("B", "C"),
            _trade_row("C", "A"),
        ]
    )
    g = build_trade_graph(trades)
    cycles = find_trade_cycles(g, max_cycle_length=5)
    assert any(set(cycle) == {"A", "B", "C"} for cycle in cycles)


def test_find_trade_cycles_ignores_acyclic_chain():
    trades = pd.DataFrame([_trade_row("A", "B"), _trade_row("B", "C")])
    g = build_trade_graph(trades)
    assert find_trade_cycles(g, max_cycle_length=5) == []


def test_find_trade_cycles_respects_max_length():
    trades = pd.DataFrame(
        [
            _trade_row("A", "B"),
            _trade_row("B", "C"),
            _trade_row("C", "D"),
            _trade_row("D", "A"),
        ]
    )
    g = build_trade_graph(trades)
    # 4-cycle excluded when max length is 3
    assert find_trade_cycles(g, max_cycle_length=3) == []
    assert len(find_trade_cycles(g, max_cycle_length=4)) >= 1


# ---------------------------------------------------------------------------
# ring_id_for
# ---------------------------------------------------------------------------


def test_ring_id_deterministic_and_order_independent():
    a = ring_id_for(["A", "B", "C"], "XLM/USDC")
    b = ring_id_for(["C", "A", "B"], "XLM/USDC")
    assert a == b
    assert len(a) == 8


def test_ring_id_varies_with_asset_pair():
    assert ring_id_for(["A", "B"], "XLM/USDC") != ring_id_for(["A", "B"], "XLM/AQUA")


# ---------------------------------------------------------------------------
# detect_wash_rings (orchestrator)
# ---------------------------------------------------------------------------


def test_detect_wash_rings_flags_dense_reciprocal_ring():
    trades = _ring_trades(["A", "B", "C"], reps=4)
    rings = detect_wash_rings(trades, asset_pair="XLM/USDC", min_ring_size=3)
    assert len(rings) >= 1
    ring = rings[0]
    assert isinstance(ring, WashRing)
    assert set(ring.members) == {"A", "B", "C"}
    assert ring.cycle_count >= 1
    assert ring.suspicion_score >= 75  # dense + reciprocal + cyclic => high


def test_detect_wash_rings_low_signal_on_sparse_market():
    rings = detect_wash_rings(_sparse_trades(20), asset_pair="XLM/USDC", min_ring_size=3)
    # A sparse acyclic market should not produce high-suspicion rings.
    assert all(r.suspicion_score < 75 for r in rings)


def test_detect_wash_rings_empty_trades():
    assert detect_wash_rings(pd.DataFrame(), asset_pair="XLM/USDC") == []


def test_detect_wash_rings_reciprocity_and_density_bounds():
    trades = _ring_trades(["A", "B", "C"], reps=2)
    ring = detect_wash_rings(trades, asset_pair="XLM/USDC", min_ring_size=3)[0]
    assert 0.0 <= ring.edge_density <= 1.0
    assert 0.0 <= ring.reciprocal_edge_ratio <= 1.0
    assert ring.size == 3
    assert ring.internal_trade_count > 0


# ---------------------------------------------------------------------------
# storage round-trip
# ---------------------------------------------------------------------------


def test_save_and_get_wash_rings(tmp_path):
    from detection.storage import get_wash_rings, save_wash_rings

    db = str(tmp_path / "rings.db")
    rings = detect_wash_rings(_ring_trades(["A", "B", "C"]), asset_pair="XLM/USDC")
    save_wash_rings(rings, db_path=db)

    stored = get_wash_rings(db_path=db)
    assert len(stored) == len(rings)
    assert stored[0]["asset_pair"] == "XLM/USDC"
    assert set(stored[0]["members"]) == {"A", "B", "C"}
    assert stored[0]["suspicion_score"] >= 0


def test_get_wash_rings_min_score_filter(tmp_path):
    from detection.storage import get_wash_rings, save_wash_rings

    db = str(tmp_path / "rings.db")
    save_wash_rings(
        detect_wash_rings(_ring_trades(["A", "B", "C"], reps=4), asset_pair="XLM/USDC"),
        db_path=db,
    )
    high = get_wash_rings(min_score=75, db_path=db)
    assert all(r["suspicion_score"] >= 75 for r in high)
