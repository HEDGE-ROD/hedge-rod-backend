from detection.risk_score import RiskScore


def test_combine_high_risk_flags_both_signals():
    score = RiskScore.combine(
        wallet="GABC",
        asset_pair="XLM/USDC",
        benford_mad=0.05,
        benford_mad_threshold=0.015,
        ml_probability=0.9,
        ml_confidence=0.95,
    )

    assert score.benford_flag is True
    assert score.ml_flag is True
    assert score.score > 70
    assert score.confidence == 95


def test_combine_low_risk_flags_neither_signal():
    score = RiskScore.combine(
        wallet="GABC",
        asset_pair="XLM/USDC",
        benford_mad=0.001,
        benford_mad_threshold=0.015,
        ml_probability=0.05,
        ml_confidence=0.8,
    )

    assert score.benford_flag is False
    assert score.ml_flag is False
    assert score.score < 30


def test_combine_score_is_clamped_to_0_100():
    score = RiskScore.combine(
        wallet="GABC",
        asset_pair="XLM/USDC",
        benford_mad=10.0,
        benford_mad_threshold=0.015,
        ml_probability=1.0,
        ml_confidence=1.0,
    )

    assert 0 <= score.score <= 100
    assert score.score == 100


def test_combine_zero_threshold_skips_benford_component():
    score = RiskScore.combine(
        wallet="GABC",
        asset_pair="XLM/USDC",
        benford_mad=0.05,
        benford_mad_threshold=0.0,
        ml_probability=0.5,
        ml_confidence=0.5,
    )

    # With a zero threshold, the score is driven entirely by the ML probability.
    assert score.score == round(0.7 * 50)
