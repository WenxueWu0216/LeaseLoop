import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";

export function newQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
}

export function renderWithQuery(ui: React.ReactElement, client = newQueryClient()) {
  return { client, ...render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>) };
}

type Route = { method?: string; path: string | RegExp; status?: number; body: unknown };

/** Minimal fetch stub: first matching route wins; records every call. */
export function mockFetch(routes: Route[]) {
  const calls: { method: string; url: string; body: unknown }[] = [];
  globalThis.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? "GET";
    calls.push({ method, url, body: init?.body ? JSON.parse(String(init.body)) : undefined });
    const route = routes.find(
      (r) => (r.method ?? "GET") === method && (typeof r.path === "string" ? url.endsWith(r.path) : r.path.test(url)),
    );
    if (!route) throw new Error(`unmocked ${method} ${url}`);
    const status = route.status ?? 200;
    // jsdom has no Response; the API client only reads ok, status and text().
    return { ok: status < 400, status, text: async () => JSON.stringify(route.body) } as Response;
  }) as typeof fetch;
  return calls;
}
