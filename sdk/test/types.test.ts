import { describe, expect, it } from "vitest";

import type {
  AssetRiskRanking,
  CircularPathPayment,
  PairCorrelation,
  RiskScore,
  ShapContribution,
  WashRing,
  WebhookAlertPayload,
  WebhookCreateRequest,
  WebhookDeadLetter,
  WebhookSubscriber,
} from "../src/types.js";

/**
 * Type-level round-trip checks: a value literal that only compiles if it
 * structurally satisfies the exported type. These exist to catch field
 * drift against `api/main.py` / `detection/risk_score.py` /
 * `detection/graph_engine.py` at compile time — `tsc --noEmit` (run via
 * `npm run typecheck` and as part of `npm test` through vitest's own
 * TS checking) fails the build if a field is renamed or removed.
 */
describe("type round-trips (compile-time checked)", () => {
  it("RiskScore matches detection.risk_score.RiskScore", () => {
    const value = {
      wallet: "GABCDEF123",
      asset_pair: "XLM/USDC",
      score: 85,
      benford_flag: true,
      ml_flag: true,
      confidence: 90,
      timestamp: "2026-06-16T12:00:00Z",
    } satisfies RiskScore;
    expect(value.score).toBeGreaterThanOrEqual(0);
    expect(value.score).toBeLessThanOrEqual(100);
  });

  it("WashRing matches detection.graph_engine.WashRing / GET /rings", () => {
    const value = {
      ring_id: "abc12345",
      asset_pair: "XLM/USDC",
      members: ["GA", "GB", "GC"],
      size: 3,
      internal_trade_count: 24,
      internal_volume: 2400.0,
      edge_density: 1.0,
      reciprocal_edge_ratio: 1.0,
      cycle_count: 6,
      longest_cycle: 3,
      suspicion_score: 100,
      timestamp: "2026-06-16T12:00:00Z",
    } satisfies WashRing;
    expect(value.members).toHaveLength(3);
  });

  it("ShapContribution matches GET /scores/{wallet}/explain entries", () => {
    const value = { feature: "benford_mad_24h", shap_value: 0.42 } satisfies ShapContribution;
    expect(typeof value.shap_value).toBe("number");
  });

  it("AssetRiskRanking matches GET /assets/risk-ranking entries", () => {
    const value = { asset_pair: "XLM/USDC", average_score: 62.5, wallet_count: 12 } satisfies AssetRiskRanking;
    expect(value.wallet_count).toBe(12);
  });

  it("PairCorrelation matches GET /correlations entries", () => {
    const value = {
      pair_a: "XLM/USDC",
      pair_b: "XLM/AQUA",
      correlation_r: 0.87,
      method: "spearman",
      shared_wallet_count: 5,
      timestamp: "2026-06-16T12:00:00Z",
    } satisfies PairCorrelation;
    expect(value.method).toBe("spearman");
  });

  it("CircularPathPayment matches GET /path-payments/circular entries", () => {
    const value = {
      transaction_hash: "abc123",
      accounts: ["GA", "GB", "GA"],
      hop_count: 2,
      cycle_volume: 500,
      is_atomic_self_payment: true,
      touches_pool: false,
      timestamp: "2026-06-16T12:00:00Z",
    } satisfies CircularPathPayment;
    expect(value.hop_count).toBe(2);
  });

  it("WebhookCreateRequest allows optional filters to be omitted", () => {
    // Explicit annotation (not `satisfies`) so the optional fields stay
    // visible on the type for the assertions below.
    const minimal: WebhookCreateRequest = { url: "https://example.com/hook", secret: "whsec_x" };
    const full: WebhookCreateRequest = {
      url: "https://example.com/hook",
      secret: "whsec_x",
      min_score: 80,
      wallet_filter: "GABC,GDEF",
      asset_pair_filter: "XLM/USDC",
    };
    expect(minimal.min_score).toBeUndefined();
    expect(full.min_score).toBe(80);
  });

  it("WebhookSubscriber matches GET /webhooks entries (masked secret)", () => {
    const value = {
      subscriber_id: "sub_123",
      url: "https://example.com/hook",
      secret: "whsec_****abcd",
      min_score: 70,
      wallet_filter: null,
      asset_pair_filter: null,
      created_at: "2026-06-16T12:00:00Z",
    } satisfies WebhookSubscriber;
    expect(value.wallet_filter).toBeNull();
  });

  it("WebhookAlertPayload matches the README's Payload Format", () => {
    const value = {
      event: "risk_score_alert",
      data: {
        wallet: "GABCDEF123",
        asset_pair: "XLM/USDC",
        score: 85,
        benford_flag: true,
        ml_flag: true,
        confidence: 90,
        timestamp: "2026-06-16T12:00:00Z",
      },
      timestamp: "2026-06-16T12:00:05Z",
    } satisfies WebhookAlertPayload;
    expect(value.event).toBe("risk_score_alert");
  });

  it("WebhookDeadLetter matches GET /webhooks/dead-letters entries", () => {
    const value = {
      id: 1,
      subscriber_id: "sub_123",
      payload: {
        event: "risk_score_alert",
        data: {
          wallet: "GABCDEF123",
          asset_pair: "XLM/USDC",
          score: 85,
          benford_flag: true,
          ml_flag: true,
          confidence: 90,
          timestamp: "2026-06-16T12:00:00Z",
        },
        timestamp: "2026-06-16T12:00:05Z",
      },
      attempt_count: 8,
      last_error: "connect ECONNREFUSED",
      created_at: "2026-06-16T12:00:00Z",
    } satisfies WebhookDeadLetter;
    expect(value.attempt_count).toBe(8);
  });
});
