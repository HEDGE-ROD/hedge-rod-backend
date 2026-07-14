/**
 * Types mirroring the HEDGE-ROD FastAPI response models.
 *
 * Kept in lockstep with:
 *  - `detection/risk_score.py`   (RiskScore)
 *  - `detection/graph_engine.py` (WashRing)
 *  - `api/main.py`               (every endpoint's return shape)
 *
 * Hand-written rather than codegen'd from `/openapi.json` so field names,
 * optionality, and nullability match the Pydantic models exactly (FastAPI's
 * generated schema collapses some of these distinctions, e.g. `str | None`
 * query params vs. required path params).
 */

/**
 * Mirrors `detection.risk_score.RiskScore`. `score` and `confidence` are
 * integers in the inclusive range 0-100.
 */
export interface RiskScore {
  wallet: string;
  asset_pair: string;
  /** 0-100; higher = more suspicious. */
  score: number;
  benford_flag: boolean;
  ml_flag: boolean;
  /** 0-100 model confidence. */
  confidence: number;
  /** ISO 8601 timestamp string, as serialized by Pydantic/FastAPI. */
  timestamp: string;
}

/** One SHAP feature contribution, as returned by `GET /scores/{wallet}/explain`. */
export interface ShapContribution {
  feature: string;
  shap_value: number;
}

/** One entry of `GET /assets/risk-ranking`. */
export interface AssetRiskRanking {
  asset_pair: string;
  average_score: number;
  wallet_count: number;
}

/** One entry of `GET /correlations`. */
export interface PairCorrelation {
  pair_a: string;
  pair_b: string;
  correlation_r: number;
  method: string;
  shared_wallet_count: number;
  timestamp: string;
}

/**
 * Response shape of `GET /amm/pools/{pool_id}/risk`.
 *
 * The `pool_id` field is injected by the endpoint on top of whatever
 * `detection.amm_engine.pool_risk_from_trade_rows` returns; the remaining
 * fields describe round-trip ratio and trader concentration for the pool.
 */
export interface PoolRisk {
  pool_id: string;
  [key: string]: unknown;
}

