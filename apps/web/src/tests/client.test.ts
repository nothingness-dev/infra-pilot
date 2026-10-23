import { afterEach, expect, it, vi } from "vitest";
import fixture from "./state.fixture.json";
afterEach(() => vi.resetModules());
const bootstrapResponse = () =>
  new Response(
    JSON.stringify({ csrf: "synthetic-ui-csrf-for-test-only", source: "mock" }),
  );

it("deduplicates bootstrap under concurrent loads and forwards abort signals", async () => {
  vi.resetModules();
  const { loadState } = await import("../data");
  const fetcher = vi.fn(async (input: RequestInfo | URL) =>
    String(input).endsWith("/session")
      ? bootstrapResponse()
      : new Response(JSON.stringify(fixture)),
  );
  vi.stubGlobal("fetch", fetcher);
  const controller = new AbortController();
  await Promise.all([
    loadState(controller.signal),
    loadState(controller.signal),
  ]);
  expect(
    fetcher.mock.calls.filter(([input]) => String(input).endsWith("/session")),
  ).toHaveLength(1);
  expect(
    vi
      .mocked(fetch)
      .mock.calls.filter(([input]) => String(input).endsWith("/state"))
      .every(([, init]) => init?.signal === controller.signal),
  ).toBe(true);
});
it("reestablishes an expired server session once", async () => {
  vi.resetModules();
  const { loadState } = await import("../data");
  let reads = 0;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/session")) return bootstrapResponse();
      return ++reads === 1
        ? new Response("{}", { status: 401 })
        : new Response(JSON.stringify(fixture));
    }),
  );
  expect((await loadState()).source).toBe("mock");
  expect(reads).toBe(2);
});
it("does not echo an invalid response or a mutation error body", async () => {
  vi.resetModules();
  const { loadState, mutate } = await import("../data");
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) =>
      String(input).endsWith("/session")
        ? bootstrapResponse()
        : new Response('{"private":"synthetic-private-value"}'),
    ),
  );
  await expect(loadState()).rejects.toThrow("INVALID_DATA");
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response("synthetic-private-value", { status: 409 })),
  );
  await expect(
    mutate("reports/INC-024/refresh", {
      revision: fixture.records[0].revision,
    }),
  ).rejects.toThrow("STALE_REVISION");
});
