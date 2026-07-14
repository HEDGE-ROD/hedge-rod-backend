import { createHmac, timingSafeEqual } from "node:crypto";

const SIGNATURE_PREFIX = "sha256=";

/**
 * Default replay-protection window, per the README's "Receivers SHOULD
 * reject timestamps older than 5 minutes" guidance.
 */
const DEFAULT_TOLERANCE_SECONDS = 5 * 60;

/**
 * Compute the `X-HEDGE-ROD-Signature` value HEDGE-ROD would send for
 * `rawBody` signed with `secret`. Exposed mainly for tests and for
 * constructing synthetic deliveries; production verification should use
 * {@link verifyWebhookSignature} instead of recomputing and `===` comparing
 * (`===` is not constant-time and leaks timing information).
 *
 * @param rawBody - The exact, unparsed request body bytes as received (as a
 *   `string` or `Buffer`). Re-serializing a parsed JSON object before
 *   hashing will almost always change the byte sequence and break
 *   verification — always hash the raw bytes.
 * @param secret - The subscriber's HMAC secret, as supplied at registration.
 */
export function computeWebhookSignature(rawBody: string | Buffer, secret: string): string {
  const digest = createHmac("sha256", secret).update(rawBody).digest("hex");
  return `${SIGNATURE_PREFIX}${digest}`;
}

/**
 * Verify a HEDGE-ROD webhook delivery's `X-HEDGE-ROD-Signature` header.
 *
 * Implements the HMAC-SHA256 scheme documented in the README's "HMAC
 * Verification" section: the header is `sha256=<hex-digest>`, where the
 * digest is `HMAC-SHA256(secret, rawBody)`. Comparison is constant-time
 * (`node:crypto`'s `timingSafeEqual`) to avoid leaking the expected digest
 * through response-time side channels.
 *
 * @param rawBody - The exact, unparsed request body bytes as received.
 *   **Do not** pass `JSON.stringify(parsedBody)` — read the raw body before
 *   any JSON parsing (e.g. via `express.raw()` / `req.text()`), since
 *   re-serialization is not guaranteed to reproduce the original bytes.
 * @param secret - The subscriber's HMAC secret, as supplied at registration.
 * @param signatureHeader - The raw value of the `X-HEDGE-ROD-Signature`
 *   header (including the `sha256=` prefix). `null`/`undefined` (a missing
 *   header) is treated as an invalid signature rather than throwing.
 * @returns `true` only if the header is present, well-formed, and matches.
 *
 * @example
 * ```ts
 * import { verifyWebhookSignature } from "@hedge-rod/sdk";
 *
 * app.post("/hedge-rod-webhook", express.raw({ type: "application/json" }), (req, res) => {
 *   const ok = verifyWebhookSignature(
 *     req.body, // Buffer — raw bytes, not yet JSON-parsed
 *     process.env.HEDGE_ROD_WEBHOOK_SECRET!,
 *     req.header("X-HEDGE-ROD-Signature"),
 *   );
 *   if (!ok) return res.status(401).send("invalid signature");
 *
 *   const payload = JSON.parse(req.body.toString("utf8"));
 *   // ... handle payload.data (a RiskScore) ...
 *   res.status(200).end();
 * });
 * ```
 */
export function verifyWebhookSignature(
  rawBody: string | Buffer,
  secret: string,
  signatureHeader: string | null | undefined,
): boolean {
  if (!signatureHeader || !signatureHeader.startsWith(SIGNATURE_PREFIX)) {
    return false;
  }
  const providedHex = signatureHeader.slice(SIGNATURE_PREFIX.length).trim();
  // Hex digests must be even-length and hex-only; reject anything else
  // before touching timingSafeEqual (which throws on length mismatch).
  if (providedHex.length === 0 || providedHex.length % 2 !== 0 || !/^[0-9a-f]+$/i.test(providedHex)) {
    return false;
  }

