const TOKEN_KEY = "leaseloop.token";
const ORG_KEY = "leaseloop.org";

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

export const session = {
  get token() {
    return storage()?.getItem(TOKEN_KEY) ?? null;
  },
  set token(value: string | null) {
    if (value) storage()?.setItem(TOKEN_KEY, value);
    else storage()?.removeItem(TOKEN_KEY);
  },
  get org() {
    return storage()?.getItem(ORG_KEY) ?? null;
  },
  set org(value: string | null) {
    if (value) storage()?.setItem(ORG_KEY, value);
    else storage()?.removeItem(ORG_KEY);
  },
};

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (session.token) headers.set("Authorization", `Token ${session.token}`);
  if (session.org) headers.set("X-Organization", session.org);
  let body = init.body;
  if (init.json !== undefined) {
    headers.set("Content-Type", "application/json");
    body = JSON.stringify(init.json);
  }
  const resp = await fetch(`/api${path}`, { ...init, headers, body });
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
