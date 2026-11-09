import { ApiError, api, session } from "./client";

type Reply = { status: number; body?: unknown };

/** fetch stub that answers each URL from a queue and records the Authorization header. */
function stubFetch(replies: Record<string, Reply[]>) {
  const calls: { url: string; auth: string | null }[] = [];
  globalThis.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, auth: new Headers(init?.headers).get("Authorization") });
    const queue = replies[url];
    const reply = queue?.length ? queue.shift()! : { status: 404 };
    return { ok: reply.status < 400, status: reply.status, text: async () => JSON.stringify(reply.body ?? null) } as Response;
  }) as typeof fetch;
  return calls;
}

beforeEach(() => {
  session.access = null;
  window.localStorage.clear();
});

test("an expired access token is refreshed once and the request retried", async () => {
  session.access = "old";
  const calls = stubFetch({
    "/api/prospects/": [{ status: 401 }, { status: 200, body: { count: 0 } }],
    "/api/auth/refresh/": [{ status: 200, body: { access: "new" } }],
  });
  await expect(api("/prospects/")).resolves.toEqual({ count: 0 });
  expect(calls.map((c) => [c.url, c.auth])).toEqual([
    ["/api/prospects/", "Bearer old"],
    ["/api/auth/refresh/", null],
    ["/api/prospects/", "Bearer new"],
  ]);
  expect(session.access).toBe("new");
});

test("concurrent 401s share a single refresh request", async () => {
  session.access = "old";
  const calls = stubFetch({
    "/api/a/": [{ status: 401 }, { status: 200, body: "a" }],
    "/api/b/": [{ status: 401 }, { status: 200, body: "b" }],
    "/api/auth/refresh/": [{ status: 200, body: { access: "new" } }],
  });
  await expect(Promise.all([api("/a/"), api("/b/")])).resolves.toEqual(["a", "b"]);
  expect(calls.filter((c) => c.url === "/api/auth/refresh/")).toHaveLength(1);
});

test("a failed refresh signs the user out", async () => {
  session.access = "old";
  stubFetch({ "/api/prospects/": [{ status: 401 }], "/api/auth/refresh/": [{ status: 401 }] });
  const expired = jest.fn();
  const stop = session.onExpired(expired);
  await expect(api("/prospects/")).rejects.toBeInstanceOf(ApiError);
  expect(expired).toHaveBeenCalledTimes(1);
  expect(session.access).toBeNull();
  stop();
});

test("auth endpoints never trigger a refresh loop", async () => {
  const calls = stubFetch({ "/api/auth/login/": [{ status: 401, body: { detail: "bad" } }] });
  await expect(api("/auth/login/", { method: "POST", json: {} })).rejects.toMatchObject({ status: 401 });
  expect(calls).toHaveLength(1);
});

test("tokens are never written to browser storage", async () => {
  stubFetch({ "/api/auth/refresh/": [{ status: 200, body: { access: "secret-jwt" } }],
              "/api/x/": [{ status: 401 }, { status: 200, body: 1 }] });
  await api("/x/");
  expect(JSON.stringify({ ...window.localStorage })).not.toContain("secret-jwt");
  expect(JSON.stringify({ ...window.sessionStorage })).not.toContain("secret-jwt");
});
