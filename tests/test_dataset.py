from detection.dataset import build_training_dataset
from detection.feature_engineering import FEATURE_NAMES
from ingestion.synthetic_data import generate_synthetic_dataset


def test_build_training_dataset_shape_and_labels():
    trades, account_metadata, events, labels = generate_synthetic_dataset(
        n_normal_accounts=5, n_wash_rings=2, ring_size=3, trades_per_normal=4, trades_per_wash=6
    )
    df = build_training_dataset(trades, labels, account_metadata=account_metadata, order_book_events=events)

    assert len(df) == len(labels)
    assert set(FEATURE_NAMES + ["wallet", "label"]).issubset(df.columns)
    assert set(df["label"].unique()).issubset({0, 1})
    assert set(df["wallet"]) == set(labels.keys())


def test_wash_accounts_show_higher_concentration_and_cancellation():
    trades, account_metadata, events, labels = generate_synthetic_dataset(
        n_normal_accounts=10, n_wash_rings=3, ring_size=3, trades_per_normal=10, trades_per_wash=20
    )
    df = build_training_dataset(trades, labels, account_metadata=account_metadata, order_book_events=events)

    normal_mean = df[df["label"] == 0]["counterparty_concentration_ratio"].mean()
    wash_mean = df[df["label"] == 1]["counterparty_concentration_ratio"].mean()
    assert wash_mean > normal_mean

    normal_cancel = df[df["label"] == 0]["order_cancellation_rate"].mean()
    wash_cancel = df[df["label"] == 1]["order_cancellation_rate"].mean()
    assert wash_cancel > normal_cancel


def test_build_training_dataset_empty_trades():
    df = build_training_dataset(trades=__import__("pandas").DataFrame(), labels={})
    assert df.empty
    assert set(FEATURE_NAMES + ["wallet", "label"]).issubset(df.columns)
