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

/** One entry of `GET /path-payments/circular`. */
export interface CircularPathPayment {
  transaction_hash: string;
  accounts: string[];
  hop_count: number;
  cycle_volume: number;
  is_atomic_self_payment: boolean;
  touches_pool: boolean;
  timestamp: string;
}

/**
 * Mirrors `detection.graph_engine.WashRing`, as returned by `GET /rings`.
 *
 * A ring is a cluster of wallets whose internal trading structure (density,
 * reciprocity, circular routing) is consistent with collusive wash trading,
 * even where no individual member crosses the per-wallet risk threshold.
 */
export interface WashRing {
  ring_id: string;
  asset_pair: string;
  members: string[];
  size: number;
  internal_trade_count: number;
  internal_volume: number;
  /** Directed edge density within the ring, 0-1. */
  edge_density: number;
  /** Fraction of directed edges whose reverse edge is also present, 0-1. */
  reciprocal_edge_ratio: number;
  cycle_count: number;
  longest_cycle: number;
  /** 0-100; higher = more suspicious. */
  suspicion_score: number;
  timestamp: string;
}

/** Request body for `POST /webhooks`, mirrors `api.main.WebhookCreate`. */
export interface WebhookCreateRequest {
  url: string;
  secret: string;
  min_score?: number;
  wallet_filter?: string | null;
  asset_pair_filter?: string | null;
}

/** Response of `POST /webhooks`. */
export interface WebhookCreateResponse {
  subscriber_id: string;
}

/** One entry of `GET /webhooks` (secrets are masked server-side). */
export interface WebhookSubscriber {
  subscriber_id: string;
  url: string;
  /** Masked; the raw secret is never returned by the API. */
  secret: string;
  min_score: number;
  wallet_filter: string | null;
  asset_pair_filter: string | null;
  created_at: string;
}

