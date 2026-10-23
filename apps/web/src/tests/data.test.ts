import { describe, it, expect, vi } from "vitest";
import fixture from "./state.fixture.json";
import {
  stateSchema,
  exportSchema,
  metric,
  savePreferences,
  readPreferences,
  defaults,
} from "../data";

describe("runtime boundary", () => {
  it.each(["unavailable", "not_collected", "collection_failed"])(
    "preserves %s logs without inventing an empty collection",
    (state) => {
      const value = JSON.parse(JSON.stringify(fixture));
      value.records[0].context.log_export = {
        state,
        received: null,
        exported: 0,
        withheld: 0,
      };
      expect(
        stateSchema.parse(value).records[0].context.log_export.received,
      ).toBeNull();
      value.records[0].context.log_export.received = 0;
      expect(stateSchema.safeParse(value).success).toBe(false);
    },
  );
  it("rejects raw extra fields in downloadable summaries", () => {
    const value = {
      profile: "infrapilot-ui-export/1",
      source: "mock",
      historical: true,
      report_id: "INC-024",
      created_at: fixture.records[0].created_at,
      counts: {
        evidence: 1,
        hypotheses: 0,
        actions: 1,
        limitations: 1,
        missing_information: 7,
      },
      capabilities: fixture.records[0].context.capabilities,
      authorization_consumed: false,
      execution_authorized: false,
      execution_performed: false,
      identity_verified: false,
      remediation_verified: false,
    };
    expect(exportSchema.safeParse(value).success).toBe(true);
    expect(
      exportSchema.safeParse({ ...value, raw_response: "synthetic-sensitive" })
        .success,
    ).toBe(false);
  });
  it("accepts the real backend projection preserving null, empty, withheld and failures", () => {
    const value = stateSchema.parse(fixture);
    expect(value.records[0].snapshot.cpu_usage_percent).toBeNull();
    expect(value.records.map((r) => r.context.log_export.state)).toEqual([
      "collection_failed",
      "exported",
      "withheld",
      "empty",
    ]);
  });
  it.each([
    "source",
    "association",
    "revision",
    "logs",
    "order",
    "executed",
    "healthy-fallback",
    "duplicate",
  ])("rejects incompatible %s data", (kind) => {
    const value = JSON.parse(JSON.stringify(fixture));
    switch (kind) {
      case "source":
        value.source = "real";
        break;
      case "association":
        value.records[0].report.service_id = "other";
        break;
      case "revision":
        value.approvals[0].revision = value.records[1].revision;
        break;
      case "logs":
        value.records[3].context.log_export.received = 99;
        break;
      case "order":
        value.records[0].context.capabilities.reverse();
        break;
      case "executed":
        value.records[0].execution_performed = true;
        break;
      case "healthy-fallback":
        value.records[0].snapshot.cpu_usage_percent = -1;
        break;
      case "duplicate":
        value.records.push(structuredClone(value.records[0]));
        break;
    }
    expect(stateSchema.safeParse(value).success).toBe(false);
  });
  it("distinguishes zero from missing values", () => {
    expect(metric(null, "%")).toBe("در دسترس نیست");
    expect(metric(0, "%")).toContain("۰");
  });
  it("stores only allowlisted harmless preferences, tolerating unavailable storage", () => {
    savePreferences({
      ...defaults,
      theme: "light",
      token: "synthetic-never-persist",
    } as typeof defaults);
    expect(readPreferences().theme).toBe("light");
    expect(localStorage.getItem("infrapilot-preferences-v1")).not.toContain(
      "synthetic",
    );
    localStorage.setItem("infrapilot-preferences-v1", "invalid");
    expect(readPreferences()).toEqual(defaults);
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw Error("disabled");
    });
    expect(savePreferences(defaults)).toBe(false);
  });
});
