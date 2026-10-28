/** Thin fetch wrapper for the FastAPI backend (same origin, cookie session + CSRF header). */

export class ApiError extends Error {
  status: number;
  code?: string;
  retryable?: boolean;
  detail?: unknown;
  constructor(message: string, status: number, extra: { code?: string; retryable?: boolean; detail?: unknown } = {}) {
    super(message);
    this.status = status;
    this.code = extra.code;
    this.retryable = extra.retryable;
    this.detail = extra.detail;
  }
  get offline() {
    return this.status === 0;
  }
}

function csrfToken(): string {
  if (typeof document === "undefined") return "";
  const m = document.cookie.match(/(?:^|;\s*)parlo_csrf=([^;]+)/);
  return m ? decodeURIComponent(m[1]) : "";
}

type Options = {
  method?: string;
  body?: unknown;
  form?: FormData;
  signal?: AbortSignal;
  /** return the raw Response (for 202 handling) */
  raw?: boolean;
};

export async function api<T = unknown>(path: string, opts: Options = {}): Promise<T> {
  const method = opts.method ?? (opts.body !== undefined || opts.form ? "POST" : "GET");
  const headers: Record<string, string> = {};
  if (method !== "GET") headers["x-csrf-token"] = csrfToken();
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["content-type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(`/api/v1${path}`, { method, headers, body, credentials: "same-origin", signal: opts.signal });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError("You're offline — check your connection.", 0, { retryable: true });
  }
  if (opts.raw) return res as unknown as T;
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const d = (data ?? {}) as { detail?: unknown; code?: string; retryable?: boolean; provider_error?: string };
    let message = typeof d.detail === "string" ? d.detail : `Request failed (${res.status})`;
    if (Array.isArray(d.detail)) message = "Please check the form and try again.";
    throw new ApiError(message, res.status, { code: d.code, retryable: d.retryable, detail: d.provider_error ?? d.detail });
  }
  return data as T;
}

export const get = <T>(path: string, signal?: AbortSignal) => api<T>(path, { signal });
export const post = <T>(path: string, body?: unknown) => api<T>(path, { method: "POST", body: body ?? {} });
export const patch = <T>(path: string, body: unknown) => api<T>(path, { method: "PATCH", body });
export const put = <T>(path: string, body: unknown) => api<T>(path, { method: "PUT", body });
export const del = <T>(path: string) => api<T>(path, { method: "DELETE" });

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return "Something went wrong";
}
