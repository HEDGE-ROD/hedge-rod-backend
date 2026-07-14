# @hedge-rod/sdk

Typed TypeScript client for the [HEDGE-ROD](../README.md) wash-trading
detection API for the Stellar DEX. Covers every endpoint exposed by
`api/main.py` (scores, alerts, asset risk ranking, correlations, AMM pool
risk, circular path payments, wash-ring detection, and webhook subscriber
management), plus a constant-time HMAC-SHA256 helper for verifying inbound
webhook deliveries.

- **Isomorphic HTTP client** — built on the global `fetch`, works in Node.js
  18+ and browsers, with a configurable request timeout and a typed error
  class.
- **Hand-written types** matched field-for-field against the FastAPI
  response models and the `RiskScore` / `WashRing` Pydantic/dataclass
  schemas — not generated from `/openapi.json`, so nullability and
  optionality reflect the actual Python types rather than FastAPI's
  necessarily-lossy JSON Schema translation.
- **`verifyWebhookSignature`** — the highest-value piece for integrators.
  Implements the exact scheme documented in the root README's "Webhook
  Alerts" section, with a constant-time comparison so verification can't
  leak timing information about the expected digest.

## Install

This package is not yet published; install it from the repo directly (e.g.
via a workspace reference, `npm pack`, or a git dependency) until it ships to
npm.

```bash
npm install @hedge-rod/sdk
```

## Quick start

```ts
import { HedgeRodClient } from "@hedge-rod/sdk";

const client = new HedgeRodClient({ baseUrl: "http://localhost:8000" });

const alerts = await client.getAlerts();
const rings = await client.getRings({ min_score: 75 });
const wallet = await client.getWalletScores("GABCDEF123...");
```

### Configuration

```ts
new HedgeRodClient({
  baseUrl: "https://api.hedge-rod.example.com",
  timeoutMs: 15_000, // default 10_000
  headers: { "X-Custom-Header": "value" }, // merged into every request
  fetch: myCustomFetch, // e.g. undici's fetch on older Node, or a test double
});
```

### Error handling

Every non-2xx response, timeout, or network failure throws
`HedgeRodApiError`:

```ts
import { HedgeRodApiError } from "@hedge-rod/sdk";

try {
  await client.getWalletScores("GUNKNOWN");
} catch (err) {
  if (err instanceof HedgeRodApiError) {
    console.error(err.status, err.path, err.body); // 404 "/scores/GUNKNOWN" {...}
    console.error(err.isNetworkError); // false — the server responded
  }
}
```

## API coverage

| Method | Endpoint |
|---|---|
| `getHealth()` | `GET /health` |
| `getScores(opts?)` | `GET /scores` |
| `getWalletScores(wallet)` | `GET /scores/{wallet}` |
| `explainScore(wallet, assetPair)` | `GET /scores/{wallet}/explain` |
| `getAlerts(opts?)` | `GET /alerts` |
| `getAssetRiskRanking()` | `GET /assets/risk-ranking` |
| `getCorrelations()` | `GET /correlations` |
| `getPoolRisk(poolId)` | `GET /amm/pools/{pool_id}/risk` |
| `getCircularPathPayments(opts?)` | `GET /path-payments/circular` |
| `getRings(opts?)` | `GET /rings` |
| `registerWebhook(body)` | `POST /webhooks` |
| `listWebhooks()` | `GET /webhooks` |
| `deleteWebhook(subscriberId)` | `DELETE /webhooks/{subscriber_id}` |
| `getDeadLetters()` | `GET /webhooks/dead-letters` |

`GetScoresOptions`, `GetAlertsOptions`, `GetRingsOptions`, and
`GetCircularPathPaymentsOptions` mirror each endpoint's query parameters
exactly (see `src/types.ts`).

## Verifying webhook signatures

HEDGE-ROD signs every webhook delivery with `X-HEDGE-ROD-Signature:
sha256=<hex-digest>`, an HMAC-SHA256 of the raw request body keyed by the
subscriber's secret (see the root README's "Webhook Alerts" → "HMAC
Verification" section). **Always verify this before trusting a payload.**

```ts
import { verifyWebhookSignature, isWebhookTimestampFresh } from "@hedge-rod/sdk";
import express from "express";

const app = express();

app.post(
  "/hedge-rod-webhook",
  express.raw({ type: "application/json" }), // raw bytes — do NOT use express.json() here
  (req, res) => {
    const signature = req.header("X-HEDGE-ROD-Signature");
    const timestamp = req.header("X-HEDGE-ROD-Timestamp");

    if (!verifyWebhookSignature(req.body, process.env.HEDGE_ROD_WEBHOOK_SECRET!, signature)) {
      return res.status(401).send("invalid signature");
    }
    if (!isWebhookTimestampFresh(timestamp)) {
      return res.status(401).send("stale delivery"); // replay-attack guard, 5 min default window
    }

    const payload = JSON.parse(req.body.toString("utf8")); // WebhookAlertPayload
    console.log(payload.data.wallet, payload.data.score);
    res.status(200).end();
  },
);
```

**Important:** `req.body` must be the *raw, unparsed* bytes. Verifying a
re-serialized `JSON.stringify(parsedBody)` will fail unpredictably, since
JSON re-serialization is not guaranteed to reproduce the exact original
byte sequence (key order, whitespace, number formatting).

`verifyWebhookSignature` and `computeWebhookSignature` are built on
`node:crypto` (`createHmac`, `timingSafeEqual`), so they require a
Node.js-compatible runtime (Node, Deno, Bun, or an edge runtime with Node
compat, e.g. Cloudflare Workers' `nodejs_compat` flag). The rest of the
client (`HedgeRodClient`) is browser-safe.

## Development

```bash
cd sdk
npm install
npm run build       # tsup -> dist/ (ESM + CJS + .d.ts)
npm run typecheck   # tsc --noEmit
npm test            # vitest run
```

## License

MIT — see [LICENSE](./LICENSE).
