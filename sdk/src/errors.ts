/**
 * Thrown for any non-2xx response, a request timeout, or a network-level
 * failure raised by `fetch` itself.
 *
 * `status` is `0` for timeouts and network errors (no HTTP response was
 * received), matching the convention that a truthy positive `status` always
 * means "the server responded".
 */
export class HedgeRodApiError extends Error {
  /** HTTP status code, or `0` for timeout / network failures. */
  readonly status: number;
  /** Parsed JSON error body, when the response was JSON and had a body. */
  readonly body: unknown;
  /** The request path, e.g. `/scores/GABC...`. */
  readonly path: string;

  constructor(message: string, options: { status: number; body?: unknown; path: string; cause?: unknown }) {
    super(message, options.cause !== undefined ? { cause: options.cause } : undefined);
    this.name = "HedgeRodApiError";
    this.status = options.status;
    this.body = options.body;
    this.path = options.path;
    Object.setPrototypeOf(this, HedgeRodApiError.prototype);
  }

  /** True when the request never reached the server (timeout or network error). */
  get isNetworkError(): boolean {
    return this.status === 0;
  }
}
