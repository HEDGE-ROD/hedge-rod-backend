import { afterEach, describe, expect, it, vi } from "vitest";

import { HedgeRodClient } from "../src/client.js";
import { HedgeRodApiError } from "../src/errors.js";
import type { RiskScore, WashRing } from "../src/types.js";

function jsonResponse(body: unknown, init: { status?: number; statusText?: string } = {}): Response {
  return new Response(JSON.stringify(body), {
    status: init.status ?? 200,
    statusText: init.statusText ?? "OK",
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("HedgeRodClient construction", () => {
  it("throws on an empty baseUrl", () => {
    expect(() => new HedgeRodClient({ baseUrl: "" })).toThrow(TypeError);
  });

  it("strips a trailing slash from baseUrl", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ status: "ok" }));
    const client = new HedgeRodClient({ baseUrl: "http://localhost:8000/", fetch: fetchMock });
    await client.getHealth();
    const calledUrl = fetchMock.mock.calls[0]?.[0] as string;
    expect(calledUrl).toBe("http://localhost:8000/health");
  });
});

describe("HedgeRodClient.getScores", () => {
  it("fetches /scores with query params and returns typed RiskScore[]", async () => {
    const scores: RiskScore[] = [
      {
        wallet: "GABC",
        asset_pair: "XLM/USDC",
        score: 85,
        benford_flag: true,
        ml_flag: true,
        confidence: 90,
        timestamp: "2026-06-16T12:00:00Z",
      },
    ];
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(scores));
    const client = new HedgeRodClient({ baseUrl: "http://localhost:8000", fetch: fetchMock });

    const result = await client.getScores({ min_score: 50, limit: 10, sort_by: "score" });

    expect(result).toEqual(scores);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/scores?min_score=50&limit=10&sort_by=score");
    expect(init.method).toBe("GET");
    expect((init.headers as Record<string, string>).Accept).toBe("application/json");
  });

  it("omits undefined query params entirely", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([]));
    const client = new HedgeRodClient({ baseUrl: "http://localhost:8000", fetch: fetchMock });
    await client.getScores();
    const url = fetchMock.mock.calls[0]?.[0] as string;
    expect(url).toBe("http://localhost:8000/scores");
  });
});

describe("HedgeRodClient.getRings", () => {
  it("fetches /rings and returns typed WashRing[]", async () => {
    const rings: WashRing[] = [
      {
        ring_id: "abc12345",
        asset_pair: "XLM/USDC",
        members: ["GA", "GB", "GC"],
        size: 3,
        internal_trade_count: 24,
        internal_volume: 2400,
        edge_density: 1.0,
        reciprocal_edge_ratio: 1.0,
        cycle_count: 6,
        longest_cycle: 3,
        suspicion_score: 100,
        timestamp: "2026-06-16T12:00:00Z",
      },
    ];
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(rings));
    const client = new HedgeRodClient({ baseUrl: "http://localhost:8000", fetch: fetchMock });

    const result = await client.getRings({ min_score: 75, asset_pair: "XLM/USDC" });

    expect(result).toEqual(rings);
    const url = fetchMock.mock.calls[0]?.[0] as string;
    expect(url).toBe("http://localhost:8000/rings?min_score=75&asset_pair=XLM%2FUSDC");
  });

  it("defaults to no query params when called with no options", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([]));
    const client = new HedgeRodClient({ baseUrl: "http://localhost:8000", fetch: fetchMock });
    await client.getRings();
    expect(fetchMock.mock.calls[0]?.[0]).toBe("http://localhost:8000/rings");
  });
});

describe("HedgeRodClient error handling", () => {
  it("throws HedgeRodApiError with parsed detail on a 404", async () => {
    // Return a fresh Response per call: a Response body can only be read once,
    // so a single reused instance would fail the second await.
    const fetchMock = vi
      .fn()
      .mockImplementation(() =>
        Promise.resolve(
          jsonResponse({ detail: "No scores found for wallet GABC" }, { status: 404, statusText: "Not Found" }),
        ),
      );
    const client = new HedgeRodClient({ baseUrl: "http://localhost:8000", fetch: fetchMock });

    let caught: unknown;
    try {
      await client.getWalletScores("GABC");
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(HedgeRodApiError);
    expect(caught).toMatchObject({ status: 404, path: "/scores/GABC" });
    expect((caught as HedgeRodApiError).body).toEqual({ detail: "No scores found for wallet GABC" });
  });

  it("URL-encodes path parameters", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([]));
    const client = new HedgeRodClient({ baseUrl: "http://localhost:8000", fetch: fetchMock });
    await client.getWalletScores("GA/BC");
    expect(fetchMock.mock.calls[0]?.[0]).toBe("http://localhost:8000/scores/GA%2FBC");
  });

  it("marks network failures with status 0 and isNetworkError true", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new Error("fetch failed"));
    const client = new HedgeRodClient({ baseUrl: "http://localhost:8000", fetch: fetchMock });

    let caught: unknown;
    try {
      await client.getHealth();
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(HedgeRodApiError);
    expect((caught as HedgeRodApiError).isNetworkError).toBe(true);
    expect((caught as HedgeRodApiError).status).toBe(0);
  });

  it("times out slow requests", async () => {
    const fetchMock = vi.fn().mockImplementation((_url: string, init: RequestInit) => {
      return new Promise((_resolve, reject) => {
        init.signal?.addEventListener("abort", () => {
          const err = new Error("This operation was aborted");
          err.name = "AbortError";
          reject(err);
        });
      });
    });
    const client = new HedgeRodClient({ baseUrl: "http://localhost:8000", fetch: fetchMock, timeoutMs: 10 });

    await expect(client.getHealth()).rejects.toThrow(/timed out/);
  }, 2000);
});

describe("HedgeRodClient webhook management", () => {
  it("POSTs a JSON body to /webhooks and returns the subscriber_id", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ subscriber_id: "sub_123" }, { status: 201 }));
    const client = new HedgeRodClient({ baseUrl: "http://localhost:8000", fetch: fetchMock });

    const result = await client.registerWebhook({
      url: "https://example.com/hook",
      secret: "whsec_abc",
      min_score: 80,
    });

    expect(result).toEqual({ subscriber_id: "sub_123" });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/webhooks");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      url: "https://example.com/hook",
      secret: "whsec_abc",
      min_score: 80,
    });
  });

  it("DELETEs /webhooks/{id}", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ status: "deactivated" }));
    const client = new HedgeRodClient({ baseUrl: "http://localhost:8000", fetch: fetchMock });
    const result = await client.deleteWebhook("sub_123");
    expect(result).toEqual({ status: "deactivated" });
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/webhooks/sub_123");
    expect(init.method).toBe("DELETE");
  });
});
