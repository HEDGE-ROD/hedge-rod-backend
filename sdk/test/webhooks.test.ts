import { createHmac } from "node:crypto";
import { describe, expect, it } from "vitest";

import { computeWebhookSignature, isWebhookTimestampFresh, verifyWebhookSignature } from "../src/webhooks.js";

// Known vector, independently computed (not via the module under test) so
// the test can't pass by mirroring a bug back at itself.
const SECRET = "whsec_test_secret";
const BODY = '{"event":"risk_score_alert","data":{"wallet":"GABC","score":85}}';
const EXPECTED_HEX = createHmac("sha256", SECRET).update(BODY).digest("hex");
const EXPECTED_HEADER = `sha256=${EXPECTED_HEX}`;

describe("computeWebhookSignature", () => {
  it("matches an independently computed HMAC-SHA256 digest", () => {
    expect(computeWebhookSignature(BODY, SECRET)).toBe(EXPECTED_HEADER);
  });

  it("accepts a Buffer body identically to the equivalent string", () => {
    expect(computeWebhookSignature(Buffer.from(BODY, "utf8"), SECRET)).toBe(EXPECTED_HEADER);
  });
});

describe("verifyWebhookSignature", () => {
  it("returns true for a valid signature (known vector)", () => {
    expect(verifyWebhookSignature(BODY, SECRET, EXPECTED_HEADER)).toBe(true);
  });

  it("returns true when the body is passed as a Buffer", () => {
    expect(verifyWebhookSignature(Buffer.from(BODY, "utf8"), SECRET, EXPECTED_HEADER)).toBe(true);
  });

  it("returns false for a tampered body", () => {
    expect(verifyWebhookSignature(BODY + "tampered", SECRET, EXPECTED_HEADER)).toBe(false);
  });

  it("returns false for the wrong secret", () => {
    expect(verifyWebhookSignature(BODY, "wrong_secret", EXPECTED_HEADER)).toBe(false);
  });

  it("returns false for a missing header", () => {
    expect(verifyWebhookSignature(BODY, SECRET, undefined)).toBe(false);
    expect(verifyWebhookSignature(BODY, SECRET, null)).toBe(false);
  });

  it("returns false for a header missing the sha256= prefix", () => {
    expect(verifyWebhookSignature(BODY, SECRET, EXPECTED_HEX)).toBe(false);
  });

  it("returns false for a malformed (non-hex) digest without throwing", () => {
    expect(verifyWebhookSignature(BODY, SECRET, "sha256=not-hex-at-all!!")).toBe(false);
  });

  it("returns false for a digest of the wrong length without throwing", () => {
    expect(verifyWebhookSignature(BODY, SECRET, "sha256=abcd")).toBe(false);
  });

  it("returns false for an empty digest", () => {
    expect(verifyWebhookSignature(BODY, SECRET, "sha256=")).toBe(false);
  });

  it("is case-insensitive on the hex digest", () => {
    expect(verifyWebhookSignature(BODY, SECRET, `sha256=${EXPECTED_HEX.toUpperCase()}`)).toBe(true);
  });
});

describe("isWebhookTimestampFresh", () => {
  const now = 1_700_000_000;

  it("accepts a timestamp within the default 5-minute window", () => {
    expect(isWebhookTimestampFresh(String(now - 60), undefined, now)).toBe(true);
  });

  it("rejects a timestamp older than the tolerance", () => {
    expect(isWebhookTimestampFresh(String(now - 600), 300, now)).toBe(false);
  });

  it("rejects a timestamp in the future beyond tolerance", () => {
    expect(isWebhookTimestampFresh(String(now + 600), 300, now)).toBe(false);
  });

  it("rejects missing or non-numeric headers", () => {
    expect(isWebhookTimestampFresh(undefined, 300, now)).toBe(false);
    expect(isWebhookTimestampFresh(null, 300, now)).toBe(false);
    expect(isWebhookTimestampFresh("not-a-number", 300, now)).toBe(false);
  });

  it("respects a custom tolerance", () => {
    expect(isWebhookTimestampFresh(String(now - 10), 5, now)).toBe(false);
    expect(isWebhookTimestampFresh(String(now - 3), 5, now)).toBe(true);
  });
});
