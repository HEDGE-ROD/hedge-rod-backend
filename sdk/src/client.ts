import { HedgeRodApiError } from "./errors.js";
import type {
  AssetRiskRanking,
  CircularPathPayment,
  GetAlertsOptions,
  GetCircularPathPaymentsOptions,
  GetRingsOptions,
  GetScoresOptions,
  HealthResponse,
  PairCorrelation,
  PoolRisk,
  RiskScore,
  ShapContribution,
  WashRing,
  WebhookCreateRequest,
  WebhookCreateResponse,
  WebhookDeadLetter,
  WebhookDeleteResponse,
  WebhookSubscriber,
} from "./types.js";

export interface HedgeRodClientOptions {
  /** Base URL of the running `api/main.py` instance, e.g. `http://localhost:8000`. */
  baseUrl: string;
  /**
   * Admin API key, sent as `X-Admin-Key`, required only for `/admin/*`
   * endpoints (not exposed by this client yet, but accepted here so the
   * option is forward-compatible).
   */
  adminKey?: string;
  /** Request timeout in milliseconds. Defaults to 10000. */
  timeoutMs?: number;
  /** Custom fetch implementation (for testing or non-standard runtimes). */
  fetch?: typeof fetch;
  /** Extra headers merged into every request. */
  headers?: Record<string, string>;
}

type QueryValue = string | number | boolean | undefined;
type QueryParams = Record<string, QueryValue>;

function buildQuery(params: QueryParams): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) {
      search.set(key, String(value));
    }
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

/**
 * Typed, fetch-based client for the HEDGE-ROD REST API.
 *
 * Works in Node.js 18+ (global `fetch`) and in browsers. Every method maps
 * 1:1 to an endpoint in `api/main.py`; response shapes are the hand-written
 * types in `./types.ts`, matched field-for-field against the FastAPI
 * response models.
 *
 * @example
 * ```ts
 * const client = new HedgeRodClient({ baseUrl: "http://localhost:8000" });
 * const alerts = await client.getAlerts();
 * ```
 */
export class HedgeRodClient {
  private readonly baseUrl: string;
  private readonly adminKey: string | undefined;
  private readonly timeoutMs: number;
  private readonly fetchImpl: typeof fetch;
  private readonly extraHeaders: Record<string, string>;

  constructor(options: HedgeRodClientOptions) {
    if (!options.baseUrl) {
      throw new TypeError("HedgeRodClient requires a non-empty baseUrl");
    }
    this.baseUrl = options.baseUrl.replace(/\/+$/, "");
    this.adminKey = options.adminKey;
    this.timeoutMs = options.timeoutMs ?? 10_000;
    const boundFetch = options.fetch ?? globalThis.fetch;
    if (!boundFetch) {
      throw new TypeError(
        "No fetch implementation available. Pass one via `options.fetch` (e.g. from undici) on runtimes without global fetch.",
      );
    }
    this.fetchImpl = boundFetch;
    this.extraHeaders = options.headers ?? {};
  }

  // ---------------------------------------------------------------------
  // Core request plumbing
  // ---------------------------------------------------------------------

  private async request<T>(
    path: string,
    init: { method?: string; query?: QueryParams; body?: unknown } = {},
  ): Promise<T> {
    const { method = "GET", query, body } = init;
    const url = `${this.baseUrl}${path}${query ? buildQuery(query) : ""}`;

    const headers: Record<string, string> = { Accept: "application/json", ...this.extraHeaders };
    if (this.adminKey) {
      headers["X-Admin-Key"] = this.adminKey;
    }
    let payload: string | undefined;
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(body);
    }

