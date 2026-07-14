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

