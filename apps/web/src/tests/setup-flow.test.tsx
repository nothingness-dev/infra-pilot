import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { SetupPage } from "../Setup";
import { App } from "../App";
import { setupBriefSchema, stateSchema, submitSetup } from "../data";
import fixture from "./state.fixture.json";

it("keeps the form on failure, retries idempotently, and sends no environment values", async () => {
  const sent: Record<string, unknown>[] = [];
  const reload = vi.fn(async () => {});
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input).endsWith("/session"))
      return new Response(JSON.stringify({ csrf: "synthetic-csrf-for-setup-only", source: "mock" }));
    const body = JSON.parse(String(init?.body));
    sent.push(body);
    if (sent.length === 1) return new Response("{}", { status: 503 });
    const { idempotency_key: _key, ...brief } = body;
    return new Response(JSON.stringify({ id: "SETUP-" + "a".repeat(32), source: "mock", operation: "setup_service",
      state: "blocked", limitation: "setup_operation_not_supported_by_gate", created_at: new Date().toISOString(),
      brief, environment_values: "not_collected", execution_authorized: false, execution_performed: false }));
  }));
  render(<SetupPage c={{ data: stateSchema.parse(fixture), date: String, busy: false,
    act: vi.fn(), reload, notify: vi.fn() }} />);
  fireEvent.change(screen.getByLabelText("نام سرویس"), { target: { value: "custom-mock-app" } });
  // This deliberately entered secret stays inside the form.
  const inputs = document.querySelectorAll<HTMLInputElement>('input[type="password"]');
  expect(inputs.length).toBeGreaterThan(0);
  fireEvent.change(inputs[0], { target: { value: "synthetic-private-canary" } });
  fireEvent.click(screen.getByRole("button", { name: /۴/ }));
  const send = screen.getByRole("button", { name: "ارسال برنامه به کارتابل تأیید عملیات" });
  fireEvent.click(send);
  await screen.findByRole("alert");
  expect(window.location.pathname).not.toBe("/approvals");
  expect(reload).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: /۱/ }));
  expect(screen.getByLabelText("نام سرویس")).toHaveValue("custom-mock-app");
  fireEvent.click(screen.getByRole("button", { name: /۴/ }));
  fireEvent.click(screen.getByRole("button", { name: "ارسال برنامه به کارتابل تأیید عملیات" }));
  await waitFor(() => expect(reload).toHaveBeenCalledOnce());
  expect(sent).toHaveLength(2);
  expect(sent[0]).toEqual(sent[1]);
  expect(JSON.stringify(sent)).not.toContain("synthetic-private-canary");
  expect(sent[0]).not.toHaveProperty("environment_values");
  expect(window.location.search).toContain("setup=SETUP-");
});

it("renders the persisted setup target in the approvals worklist with no approval or execution claim", async () => {
  const state = stateSchema.parse(fixture);
  state.setup_requests.push({ id: "SETUP-" + "b".repeat(32), source: "mock", operation: "setup_service", state: "blocked",
    limitation: "setup_operation_not_supported_by_gate", created_at: new Date().toISOString(),
    brief: { service_id: "persisted-mock-app", platform: "python", plan: "standard-1gb", custom_domain: "app.example.com", environment_keys: ["DATABASE_URL"] },
    environment_values: "not_collected", execution_authorized: false, execution_performed: false });
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => new Response(JSON.stringify(
    String(input).endsWith("/session") ? { csrf: "synthetic-csrf-for-setup-only", source: "mock" } : state))));
  window.history.replaceState({}, "", "/approvals?setup=" + state.setup_requests[0].id);
  render(<App />);
  const plan = await screen.findByRole("article", { name: "برنامه persisted-mock-app" });
  expect(plan).toHaveTextContent(state.setup_requests[0].id);
  expect(plan).toHaveTextContent("setup_service");
  expect(plan).toHaveTextContent("مسدود");
  expect(within(plan).queryByRole("button", { name: /تأیید/ })).toBeNull();
});

it("allows only one in-flight submission even for rapid repeated clicks", async () => {
  let finish!: (response: Response) => void;
  let posts = 0;
  const pending = new Promise<Response>((resolve) => { finish = resolve; });
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    if (String(input).endsWith("/session"))
      return new Response(JSON.stringify({ csrf: "synthetic-csrf-for-setup-only", source: "mock" }));
    posts++;
    return pending;
  }));
  render(<SetupPage c={{ data: stateSchema.parse(fixture), date: String, busy: false,
    act: vi.fn(), reload: vi.fn(), notify: vi.fn() }} />);
  fireEvent.click(screen.getByRole("button", { name: /۴/ }));
  const button = screen.getByRole("button", { name: "ارسال برنامه به کارتابل تأیید عملیات" });
  fireEvent.click(button);
  fireEvent.click(button);
  await waitFor(() => expect(posts).toBe(1));
  expect(button).toBeDisabled();
  finish(new Response("{}", { status: 503 }));
  await screen.findByRole("alert");
});

it("rejects malformed domains, duplicate keys and excessive environment names before submitting", () => {
  const base = { service_id: "mock-service", platform: "python", plan: "standard-1gb", custom_domain: "", environment_keys: [] };
  for (const domain of ["bad..example.com", "bad_.example.com", "-bad.example.com", "https://example.com", "a".repeat(64) + ".com"])
    expect(setupBriefSchema.safeParse({ ...base, custom_domain: domain }).success).toBe(false);
  expect(setupBriefSchema.safeParse({ ...base, custom_domain: "a.example.ir" }).success).toBe(true);
  expect(setupBriefSchema.safeParse({ ...base, environment_keys: ["KEY", "KEY"] }).success).toBe(false);
  expect(setupBriefSchema.safeParse({ ...base, environment_keys: Array.from({ length: 31 }, (_, n) => "KEY_" + n) }).success).toBe(false);
});

it("never reflects a variable value in validation feedback and disables invalid submission", () => {
  render(<SetupPage c={{ data: stateSchema.parse(fixture), date: String, busy: false,
    act: vi.fn(), reload: vi.fn(), notify: vi.fn() }} />);
  fireEvent.change(screen.getAllByLabelText("نام کلید متغیر")[0], { target: { value: "" } });
  fireEvent.change(screen.getAllByLabelText("مقدار متغیر")[0], { target: { value: "synthetic-validation-canary" } });
  fireEvent.click(screen.getByRole("button", { name: /۳ ·/ }));
  expect(document.body.textContent).not.toContain("synthetic-validation-canary");
  expect(screen.getByText("نام متغیر محیطی دارای مقدار وارد نشده است.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /۴ ·/ }));
  expect(screen.getByRole("button", { name: "ارسال برنامه به کارتابل تأیید عملیات" })).toBeDisabled();
});

it("does not claim SSL is active or provide unverified DNS instructions", () => {
  render(<SetupPage c={{ data: stateSchema.parse(fixture), date: String, busy: false,
    act: vi.fn(), reload: vi.fn(), notify: vi.fn() }} />);
  fireEvent.click(screen.getByRole("button", { name: /۲ ·/ }));
  expect(screen.queryByText("رایگان و فعال")).toBeNull();
  expect(document.body.textContent).not.toContain("cname.iran.liara.ir");
  expect(screen.getByText("هیچ گواهی بررسی یا صادر نشده است")).toBeInTheDocument();
});

it("does not automatically move a failed mutation to a new session", async () => {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    calls.push(String(input));
    return new Response("{}", { status: 401 });
  }));
  await expect(submitSetup({ service_id: "mock-service", platform: "python", plan: "standard-1gb", custom_domain: "", environment_keys: [] }, crypto.randomUUID())).rejects.toThrow();
  expect(calls.filter((url) => url.endsWith("/setup-requests"))).toHaveLength(1);
  expect(calls.some((url) => url.endsWith("/session"))).toBe(false);
});

it("rejects a valid-looking saved result associated with another target", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
    id: "SETUP-" + "a".repeat(32), source: "mock", operation: "setup_service", state: "blocked",
    limitation: "setup_operation_not_supported_by_gate", created_at: new Date().toISOString(),
    brief: { service_id: "another-target", platform: "python", plan: "standard-1gb", custom_domain: "", environment_keys: [] },
    environment_values: "not_collected", execution_authorized: false, execution_performed: false,
  }))));
  await expect(submitSetup({ service_id: "mock-service", platform: "python", plan: "standard-1gb", custom_domain: "", environment_keys: [] }, crypto.randomUUID())).rejects.toThrow("SETUP_ASSOCIATION_FAILED");
});

it("does not navigate away from another page when an unmounted submission completes", async () => {
  let finish!: (value: Response) => void;
  let brief: Record<string, unknown>;
  const pending = new Promise<Response>((resolve) => { finish = resolve; });
  const reload = vi.fn(async () => {});
  vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    const { idempotency_key: _key, ...fields } = JSON.parse(String(init?.body));
    brief = fields;
    return pending;
  }));
  const view = render(<SetupPage c={{ data: stateSchema.parse(fixture), date: String, busy: false,
    act: vi.fn(), reload, notify: vi.fn() }} />);
  fireEvent.click(screen.getByRole("button", { name: /۴ ·/ }));
  fireEvent.click(screen.getByRole("button", { name: "ارسال برنامه به کارتابل تأیید عملیات" }));
  await waitFor(() => expect(brief).toBeDefined());
  view.unmount();
  window.history.replaceState({}, "", "/reports");
  await act(async () => finish(new Response(JSON.stringify({
    id: "SETUP-" + "c".repeat(32), source: "mock", operation: "setup_service", state: "blocked",
    limitation: "setup_operation_not_supported_by_gate", created_at: new Date().toISOString(), brief,
    environment_values: "not_collected", execution_authorized: false, execution_performed: false,
  }))));
  expect(window.location.pathname).toBe("/reports");
  expect(reload).not.toHaveBeenCalled();
});
