import {
  render,
  screen,
  waitFor,
  within,
  fireEvent,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import fixture from "./state.fixture.json";
import { App } from "../App";
import { DataGrid, Dialog } from "../ui";

let current: typeof fixture;
let calls: { url: string; init?: RequestInit }[];
beforeEach(() => {
  current = structuredClone(fixture);
  calls = [];
  current.approvals[0].expires_at = new Date(Date.now() + 300000).toISOString();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, init });
      if (url.endsWith("/session"))
        return new Response(
          JSON.stringify({
            csrf: "synthetic-test-csrf-000000000000",
            source: "mock",
          }),
        );
      if (url.endsWith("/state")) return new Response(JSON.stringify(current));
      if (url.endsWith("/decision")) {
        const body = JSON.parse(String(init?.body));
        current.approvals[0].state =
          body.decision === "approve" ? "approved" : "rejected";
        current.approvals[0].can_decide = false;
        return new Response("{}");
      }
      return new Response("{}");
    }),
  );
});
const ready = () =>
  screen.findByRole("heading", { name: "مرکز فرمان زیرساخت", level: 1 });

describe("integrated UI", () => {
  it("filters services without manufacturing healthy data", async () => {
    window.history.replaceState({}, "", "/services");
    render(<App />);
    const user = userEvent.setup();
    await screen.findByRole("heading", { name: "سرویس‌های پروژه" });
    await user.selectOptions(
      screen.getByRole("combobox", { name: "فیلتر سلامت سرویس" }),
      "healthy",
    );
    expect(screen.getByText("نتیجه‌ای پیدا نشد")).toBeInTheDocument();
    expect(
      screen.getByRole("combobox", { name: "دامنهٔ منبع" }),
    ).toBeDisabled();
  });
  it("navigates from a ranked hypothesis to the exact associated evidence", async () => {
    const record = current.records[1],
      target = record.report.evidence[1];
    Object.assign(record.report, {
      hypotheses: [
        {
          hypothesis_id: "synthetic-hypothesis",
          explanation: "Synthetic support",
          confidence: 0.7,
          evidence_ids: [target.evidence_id],
        },
      ],
    });
    window.history.replaceState({}, "", "/analysis?incident=" + record.id);
    render(<App />);
    const user = userEvent.setup();
    await screen.findByText("Synthetic support");
    await user.click(
      screen.getByRole("link", { name: "بررسی شاهد " + target.evidence_id }),
    );
    expect(window.location.search).toContain("evidence=");
    expect(document.querySelector(".evidence-quote")).toHaveTextContent(
      target.description,
    );
  });
  it("discards a late response after the corresponding view was unmounted", async () => {
    let release!: (r: Response) => void;
    const stale = JSON.parse(JSON.stringify(fixture));
    stale.records[0].title = "stale-private-view";
    const late = new Promise<Response>((resolve) => {
      release = resolve;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) =>
        String(input).endsWith("/session")
          ? new Response(
              JSON.stringify({
                csrf: "synthetic-test-csrf-000000000000",
                source: "mock",
              }),
            )
          : late,
      ),
    );
    const first = render(<App />);
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    first.unmount();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify(current))),
    );
    render(<App />);
    await ready();
    release(new Response(JSON.stringify(stale)));
    await waitFor(() =>
      expect(document.body).not.toHaveTextContent("stale-private-view"),
    );
  });
  it("follows system preference and updates when the OS theme changes", async () => {
    localStorage.setItem(
      "infrapilot-preferences-v1",
      JSON.stringify({
        theme: "system",
        timezone: "UTC",
        notifications: false,
      }),
    );
    let changed!: () => void;
    const media = {
      matches: false,
      addEventListener: (_event: string, fn: () => void) => {
        changed = fn;
      },
      removeEventListener: vi.fn(),
    };
    vi.spyOn(window, "matchMedia").mockReturnValue(
      media as unknown as MediaQueryList,
    );
    render(<App />);
    await ready();
    expect(document.documentElement.dataset.theme).toBe("light");
    media.matches = true;
    changed();
    expect(document.documentElement.dataset.theme).toBe("dark");
  });
  it("renders backend text as escaped text, including hostile-looking markup", async () => {
    current.records[0].report.summary =
      "<img src=x onerror=alert(1)>synthetic-safe-markup";
    render(<App />);
    await ready();
    expect(
      screen.getByText(current.records[0].report.summary),
    ).toBeInTheDocument();
    expect(document.querySelector('img[src="x"]')).toBeNull();
  });
  it("opens and closes the responsive navigation and clears it on route changes", async () => {
    render(<App />);
    await ready();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "باز کردن فهرست" }));
    expect(document.querySelector(".sidebar")).toHaveClass("open");
    await user.click(
      within(screen.getByRole("navigation")).getByRole("link", {
        name: "سرویس‌ها",
      }),
    );
    expect(document.querySelector(".sidebar")).not.toHaveClass("open");
  });
  it("disables approval when its advertised validity has ended", async () => {
    current.approvals[0].expires_at = new Date(Date.now() - 1000).toISOString();
    window.history.replaceState({}, "", "/approvals");
    render(<App />);
    expect(
      await screen.findByRole("button", { name: "تأیید درخواست" }),
    ).toBeDisabled();
  });
  it.each([
    ["/", "مرکز فرمان زیرساخت"],
    ["/services", "سرویس‌های پروژه"],
    ["/services/MOCK-service", "سرویس آزمایشی"],
    ["/incidents", "مرکز رخدادها"],
    ["/incidents/INC-024", "جمع‌آوری ناقص شواهد"],
    ["/analysis", "تحلیل شفاف؛ تصمیم قابل بررسی"],
    ["/approvals", "مرکز تأیید عملیات"],
    ["/reports", "گزارش‌ها و ردپای تصمیم"],
    ["/connections/liara", "اتصال امن به Liara"],
    ["/settings", "تنظیمات فضای کاری"],
  ])("renders %s using validated backend data", async (path, title) => {
    window.history.replaceState({}, "", path);
    render(<App />);
    await waitFor(() =>
      expect(
        screen.queryByText("در حال دریافت گزارش‌های آزمایشی…"),
      ).not.toBeInTheDocument(),
    );
    expect(screen.getByRole("main")).toHaveTextContent(title);
    expect(screen.getByRole("button", { name: "REAL" })).toBeDisabled();
    expect(document.body).not.toHaveTextContent("synthetic-test-csrf");
  });
  it("navigates by sidebar, persists themes and keeps DEMO provenance", async () => {
    render(<App />);
    await ready();
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "تم روشن" }));
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem("infrapilot-preferences-v1")).toContain(
      "light",
    );
    await user.click(
      within(screen.getByRole("navigation")).getByRole("link", {
        name: "رخدادها",
      }),
    );
    expect(window.location.pathname).toBe("/incidents");
    expect(screen.getByRole("main")).toHaveTextContent("نمایشی");
  });
  it("requires explicit acknowledgement and records a backend decision without execution", async () => {
    window.history.replaceState({}, "", "/approvals");
    render(<App />);
    const user = userEvent.setup();
    await screen.findByRole("heading", { level: 1, name: "مرکز تأیید عملیات" });
    const approve = screen.getByRole("button", { name: "تأیید درخواست" });
    await user.click(approve);
    const dialog = screen.getByRole("dialog");
    const confirm = within(dialog)
      .getAllByRole("button")
      .find((b) => b.textContent?.includes("ثبت"))!;
    expect(confirm).toBeDisabled();
    await user.click(within(dialog).getByRole("checkbox"));
    await user.click(confirm);
    await waitFor(() =>
      expect(calls.some((c) => c.url.endsWith("/decision"))).toBe(true),
    );
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(
      calls
        .filter((c) => c.init?.method === "POST")
        .every((c) => !c.url.includes("execute")),
    ).toBe(true);
    expect(screen.getByRole("main")).toHaveTextContent("تأیید شده");
  });
  it("fails closed on a malformed response and does not display raw server errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(
            JSON.stringify({ private: "synthetic-private-payload" }),
          ),
      ),
    );
    render(<App />);
    await screen.findByRole("button", { name: "تلاش دوباره" });
    expect(document.body).not.toHaveTextContent("synthetic-private-payload");
    expect(
      screen.queryByRole("button", { name: "ثبت تصمیم" }),
    ).not.toBeInTheDocument();
  });
  it("shows a safe error when backend fails", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("sensitive-response", { status: 503 })),
    );
    render(<App />);
    await screen.findByRole("button", { name: "تلاش دوباره" });
    expect(document.body).not.toHaveTextContent("sensitive-response");
  });
  it("searches, paginates, sorts and never retains a filtered-out selection", async () => {
    const rows = [
      { id: "a", title: "Alpha" },
      { id: "b", title: "Beta" },
      { id: "c", title: "Gamma" },
    ];
    render(
      <DataGrid
        rows={rows}
        columns={[
          { title: "Name", cell: (r) => r.title, sort: (r) => r.title },
        ]}
        searchLabel="Find"
        searchValue={(r) => r.title}
        preview={(r) => <h2>{r.id}</h2>}
      />,
    );
    const user = userEvent.setup();
    await user.selectOptions(screen.getByRole("combobox"), "2");
    await user.click(screen.getByRole("button", { name: "صفحهٔ بعد" }));
    expect(screen.getByRole("heading")).toHaveTextContent("c");
    await user.type(screen.getByRole("textbox", { name: "Find" }), "Beta");
    expect(screen.getByRole("heading")).toHaveTextContent("b");
    await user.clear(screen.getByRole("textbox", { name: "Find" }));
    await user.type(screen.getByRole("textbox", { name: "Find" }), "nothing");
    expect(screen.getByText("نتیجه‌ای پیدا نشد")).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "b" }),
    ).not.toBeInTheDocument();
  });
  it("supports dialog cancellation", () => {
    const close = vi.fn();
    render(
      <Dialog title="Review" onClose={close}>
        <p>Mock</p>
      </Dialog>,
    );
    fireEvent(
      screen.getByRole("dialog"),
      new Event("cancel", { bubbles: false, cancelable: true }),
    );
    expect(close).toHaveBeenCalledOnce();
  });
});
