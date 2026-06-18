from sklearn.ensemble import RandomForestClassifier

from detection.shap_explainer import explain_score, top_contributing_features


def _trained_model():
    X = [[0, 0], [0, 1], [1, 0], [1, 1]] * 5
    y = [0, 0, 0, 1] * 5
    model = RandomForestClassifier(n_estimators=10, random_state=0)
    model.fit(X, y)
    return model


def test_explain_score_returns_value_per_feature():
    model = _trained_model()
    feature_vector = {"feature_a": 1.0, "feature_b": 0.0}

    explanation = explain_score(model, feature_vector)

    assert set(explanation.keys()) == {"feature_a", "feature_b"}
    assert all(isinstance(v, float) for v in explanation.values())


def test_top_contributing_features_orders_by_absolute_value():
    explanation = {"a": 0.1, "b": -0.9, "c": 0.5}

    top = top_contributing_features(explanation, n=2)

    assert top[0][0] == "b"
    assert top[1][0] == "c"
    assert len(top) == 2
