const ORG_KEY = "leaseloop.org";
const AUTH_PATHS = new Set(["/auth/login/", "/auth/refresh/", "/auth/logout/"]);

export class ApiError extends Error {
  constructor(
    public status: number,
    public body: unknown,
  ) {
    super(`API ${status}`);
  }
}

function storage(): Storage | null {
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

// The access token lives only in memory: page scripts injected via XSS can't lift it
// from localStorage, and it is gone when the tab closes. The refresh token is an
// HttpOnly cookie the browser sends to /api/auth/ only; this code never sees it.
let accessToken: string | null = null;
let refreshing: Promise<boolean> | null = null;
const expiredListeners = new Set<() => void>();

export const session = {
  get access() {
    return accessToken;
  },
  set access(value: string | null) {
    accessToken = value;
  },
  get org() {
    return storage()?.getItem(ORG_KEY) ?? null;
  },
  set org(value: string | null) {
    if (value) storage()?.setItem(ORG_KEY, value);
    else storage()?.removeItem(ORG_KEY);
  },
  /** Called when a refresh fails, i.e. the user must sign in again. */
  onExpired(listener: () => void) {
    expiredListeners.add(listener);
    return () => {
      expiredListeners.delete(listener);
    };
  },
};

/** Trade the refresh cookie for a new access token. Concurrent callers share one request. */
export function refreshAccess(): Promise<boolean> {
  refreshing ??= fetch("/api/auth/refresh/", { method: "POST", credentials: "same-origin" })
    .then(async (resp) => {
      if (!resp.ok) return false;
      accessToken = (JSON.parse(await resp.text()) as { access: string }).access;
      return true;
    })
    .catch(() => false)
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

function send(path: string, init: RequestInit & { json?: unknown }): Promise<Response> {
  const headers = new Headers(init.headers);
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (session.org) headers.set("X-Organization", session.org);
  let body = init.body;
  if (init.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.json);
  }
  return fetch(`/api${path}`, { ...init, headers, body, credentials: "same-origin" });
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  let resp = await send(path, init);
  if (resp.status === 401 && !AUTH_PATHS.has(path)) {
    // Access token expired (or missing after a reload): refresh once, then retry.
    if (await refreshAccess()) {
      resp = await send(path, init);
    } else {
      accessToken = null;
      expiredListeners.forEach((listener) => listener());
    }
  }
  const text = await resp.text();
  const data = text ? JSON.parse(text) : null;
  if (!resp.ok) throw new ApiError(resp.status, data);
  return data as T;
}

export function query(params: Record<string, string | number | boolean | null | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  }
  const s = q.toString();
  return s ? `?${s}` : "";
}
