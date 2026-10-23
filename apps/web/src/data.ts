import { z } from "zod";

const text = z.string().max(16000);
const stamp = z.string().datetime({ offset: true });
const flags = {
  authorization_consumed: z.literal(false),
  execution_authorized: z.literal(false),
  execution_performed: z.literal(false),
  remediation_verified: z.literal(false),
  identity_verified: z.literal(false),
};
const snapshot = z.object({
  service_id: text,
  data_source: z.literal("mock"),
  status: z.enum(["unknown", "healthy", "degraded", "unhealthy"]),
  cpu_usage_percent: z.number().finite().min(0).max(100).nullable(),
  ram_usage_mib: z.number().finite().min(0).nullable(),
  http_status: z.number().int().min(100).max(599).nullable(),
  response_time_ms: z.number().finite().min(0).nullable(),
  timestamp: stamp.nullable(),
});
const evidence = z.object({
  evidence_id: text,
  kind: z.enum(["status", "http", "metric", "log"]),
  description: text,
});
const hypothesis = z.object({
  hypothesis_id: text,
  explanation: text,
  confidence: z.number().min(0).max(1),
  evidence_ids: z.array(text),
});
const action = z.object({
  action_id: text,
  title: text,
  description: text,
  risk_level: z.enum(["unknown", "low", "medium", "high"]),
  requires_approval: z.boolean(),
  status: z.literal("not_executed"),
});
const report = z.object({
  service_id: text,
  data_source: z.literal("mock"),
  summary: text,
  evidence: z.array(evidence).max(100),
  hypotheses: z.array(hypothesis).max(100),
  actions: z.array(action).max(100),
  missing_information: z.array(text),
  limitations: z.array(text),
});
const capability = z.object({
  capability: z.enum(["service", "deployment", "logs", "metrics"]),
  availability: z.enum([
    "available",
    "unavailable",
    "not_collected",
    "authentication_failed",
    "permission_denied",
    "not_found",
    "failed",
    "unsupported",
    "unverified",
  ]),
  error_code: z.string().max(64).nullable(),
  http_status: z.number().int().min(100).max(599).nullable(),
  retryable: z.boolean().nullable(),
  collected_at: stamp.nullable(),
});
const logExport = z.object({
  state: z.enum([
    "exported",
    "partially_exported",
    "withheld",
    "empty",
    "unavailable",
    "not_collected",
    "collection_failed",
  ]),
  received: z.number().int().min(0).nullable(),
  exported: z.number().int().min(0),
  withheld: z.number().int().min(0),
});
const context = z.object({
  contract_version: z.literal("provider-collection-context/0.2-draft"),
  service_id: text,
  data_source: z.literal("mock"),
  capabilities: z.array(capability).length(4),
  log_export: logExport,
  limitations: z.array(text),
  collection_started_at: stamp,
  collection_finished_at: stamp,
  snapshot_digest: z.string().regex(/^sha256:[a-f0-9]{64}$/),
});
export const recordSchema = z
  .object({
    id: text,
    title: text,
    lifecycle: z.enum(["active", "review", "closed"]),
    lifecycle_is_demo: z.literal(true),
    revision: z.string().uuid(),
    scenario: z.enum(["partial_failure", "exported", "withheld", "empty"]),
    created_at: stamp,
    history_id: text,
    snapshot,
    report,
    context,
    source: z.literal("mock"),
    ...flags,
  })
  .superRefine((value, ctx) => {
    const bad = () =>
      ctx.addIssue({ code: "custom", message: "Invalid association" });
    if (
      value.snapshot.service_id !== value.report.service_id ||
      value.report.service_id !== value.context.service_id
    )
      bad();
    for (const list of [
      value.report.evidence.map((e) => e.evidence_id),
      value.report.actions.map((a) => a.action_id),
      value.report.hypotheses.map((h) => h.hypothesis_id),
    ])
      if (new Set(list).size !== list.length) bad();
    if (
      value.report.hypotheses.some(
        (h, i, list) =>
          h.evidence_ids.some(
            (id) => !value.report.evidence.some((e) => e.evidence_id === id),
          ) ||
          (i > 0 && list[i - 1].confidence < h.confidence),
      )
    )
      bad();
    if (
      value.context.capabilities.map((c) => c.capability).join(",") !==
      "service,deployment,logs,metrics"
    )
      bad();
    const logs = value.context.log_export;
    if (
      ["unavailable", "not_collected", "collection_failed"].includes(
        logs.state,
      ) &&
      (logs.received !== null || logs.exported !== 0 || logs.withheld !== 0)
    )
      bad();
    if (
      ["exported", "partially_exported", "withheld"].includes(logs.state) &&
      (logs.received === null || logs.received <= 0)
    )
      bad();
    if (
      logs.state === "exported" &&
      (logs.exported === 0 || logs.withheld !== 0)
    )
      bad();
    if (
      logs.state === "partially_exported" &&
      (logs.exported === 0 || logs.withheld === 0)
    )
      bad();
    if (
      Date.parse(value.context.collection_started_at) >
      Date.parse(value.context.collection_finished_at)
    )
      bad();
    if (
      logs.received !== null &&
      logs.received !== logs.exported + logs.withheld
    )
      bad();
    if (
      (logs.state === "empty" &&
        (logs.received !== 0 || logs.exported || logs.withheld)) ||
      (logs.state === "withheld" &&
        (logs.exported !== 0 || logs.withheld === 0))
    )
      bad();
  });
const audit = z.object({
  kind: z.enum([
    "approval_requested",
    "approval_granted",
    "approval_rejected",
    "approval_expired",
    "authorization_denied",
    "authorization_consumed",
  ]),
  reason: text,
  occurred_at: stamp,
});
export const approvalSchema = z.object({
  id: text,
  record_id: text,
  revision: z.string().uuid(),
  state: z.enum(["pending", "approved", "rejected", "expired", "consumed"]),
  created_at: stamp,
  expires_at: stamp,
  historical: z.boolean(),
  operation: z.literal("restart_service"),
  separate_demo: z.literal(true),
  grace_period_seconds: z.number().int().min(0).max(600),
  policy_category: z.literal("sensitive_service_operation"),
  can_decide: z.boolean(),
  audit: z.array(audit),
  ...flags,
});
export function validSetupDomain(value: string): boolean {
  return value === "" || (value.length <= 253 && value.split(".").length >= 2 &&
    value.split(".").every((label) => /^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$/.test(label)));
}
export const setupBriefSchema = z.object({
  service_id: z.string().regex(/^[a-z0-9][a-z0-9-]{1,62}$/),
  platform: z.enum(["nodejs", "python", "docker", "go", "php", "static"]),
  plan: z.enum(["starter-256mb", "standard-1gb", "pro-2gb"]),
  custom_domain: z.string().max(253).refine(validSetupDomain),
  environment_keys: z.array(z.string().regex(/^[A-Z_][A-Z0-9_]{0,63}$/)).max(30)
    .refine((keys) => new Set(keys).size === keys.length),
}).strict();
export const setupRequestSchema = z.object({
  id: z.string().regex(/^SETUP-[a-f0-9]{32}$/),
  source: z.literal("mock"),
  operation: z.literal("setup_service"),
  state: z.literal("blocked"),
  limitation: z.literal("setup_operation_not_supported_by_gate"),
  created_at: stamp,
  brief: setupBriefSchema,
  environment_values: z.literal("not_collected"),
  preparation: z.object({
    state: z.literal("blocked"),
    step_keys: z.array(z.string().regex(/^[a-z_]+$/)).min(1).max(20),
    missing_dependencies: z.array(z.string().regex(/^[a-z_]+$/)).min(1).max(20),
  }).strict().optional(),
  execution_authorized: z.literal(false),
  execution_performed: z.literal(false),
}).strict();
export type SetupBrief = z.infer<typeof setupBriefSchema>;

export const stateSchema = z
  .object({
    version: z.literal("infrapilot-ui/1-mock"),
    source: z.literal("mock"),
    real_available: z.literal(false),
    service: z.object({ id: text, name: text, project: text }),
    records: z.array(recordSchema).min(1).max(20),
    approvals: z.array(approvalSchema).max(100),
    setup_requests: z.array(setupRequestSchema).max(100).default([]),
    connection: z.object({
      state: z.literal("not_verified"),
      logs_window: z.literal("not_configured"),
    }),
    ...flags,
  })
  .superRefine((value, ctx) => {
    if (new Set(value.setup_requests.map((p) => p.id)).size !== value.setup_requests.length)
      ctx.addIssue({ code: "custom", message: "Invalid setup catalog" });
    const ids = value.records.map((r) => r.id);
    if (
      new Set(value.approvals.map((a) => a.id)).size !== value.approvals.length
    )
      ctx.addIssue({ code: "custom", message: "Invalid approval catalog" });
    if (
      new Set(ids).size !== ids.length ||
      value.records.some((r) => r.snapshot.service_id !== value.service.id)
    )
      ctx.addIssue({ code: "custom", message: "Invalid catalog" });
    for (const a of value.approvals) {
      const r = value.records.find((r) => r.id === a.record_id);
      if (
        !r ||
        (!a.historical && r.revision !== a.revision) ||
        (a.can_decide && (a.state !== "pending" || a.historical))
      )
        ctx.addIssue({
          code: "custom",
          message: "Invalid approval association",
        });
    }
  });
export type UiState = z.infer<typeof stateSchema>;
export type Incident = z.infer<typeof recordSchema>;
export type Approval = z.infer<typeof approvalSchema>;
export const exportSchema = z
  .object({
    profile: z.literal("infrapilot-ui-export/1"),
    source: z.literal("mock"),
    historical: z.literal(true),
    report_id: text,
    created_at: stamp,
    counts: z
      .object({
        evidence: z.number().int().nonnegative(),
        hypotheses: z.number().int().nonnegative(),
        actions: z.number().int().nonnegative(),
        limitations: z.number().int().nonnegative(),
        missing_information: z.number().int().nonnegative(),
      })
      .strict(),
    capabilities: z.array(capability.strict()).length(4),
    ...flags,
  })
  .strict();

let csrf = "";
let session: Promise<void> | null = null;
export function bootstrap(): Promise<void> {
  if (!session)
    session = fetch("/api/ui/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
      credentials: "same-origin",
    })
      .then(async (r) => {
        if (!r.ok) throw new Error("SESSION_UNAVAILABLE");
        csrf = z
          .object({
            csrf: z.string().min(20).max(100),
            source: z.literal("mock"),
          })
          .parse(await r.json()).csrf;
      })
      .catch(() => {
        session = null;
        throw new Error("SESSION_UNAVAILABLE");
      });
  return session;
}
export async function loadState(signal?: AbortSignal): Promise<UiState> {
  await bootstrap();
  let r = await fetch("/api/ui/state", { signal, credentials: "same-origin" });
  if (r.status === 401) {
    session = null;
    await bootstrap();
    r = await fetch("/api/ui/state", { signal, credentials: "same-origin" });
  }
  if (!r.ok) throw new Error("BACKEND_UNAVAILABLE");
  try {
    return stateSchema.parse(await r.json());
  } catch {
    throw new Error("INVALID_DATA");
  }
}
export async function mutate(path: string, payload: object): Promise<void> {
  const r = await fetch("/api/ui/" + path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-UI-CSRF": csrf },
    body: JSON.stringify(payload),
  });
  if (!r.ok)
    throw new Error(r.status === 409 ? "STALE_REVISION" : "MUTATION_FAILED");
}

export async function submitSetup(brief: SetupBrief, idempotencyKey: string) {
  const payload = { ...setupBriefSchema.parse(brief), idempotency_key: idempotencyKey };
  await bootstrap();
  const send = () => fetch("/api/ui/setup-requests", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-UI-CSRF": csrf },
    body: JSON.stringify(payload),
  });
  const response = await send();
  // A mutation must never migrate an ambiguous retry into a new session.
  // The original idempotency scope may already contain the saved proposal.
  if (!response.ok) throw new Error(response.status === 409 ? "IDEMPOTENCY_CONFLICT" : "SETUP_FAILED");
  const saved = setupRequestSchema.parse(await response.json());
  if (JSON.stringify(saved.brief) !== JSON.stringify(setupBriefSchema.parse(brief)))
    throw new Error("SETUP_ASSOCIATION_FAILED");
  return saved;
}

export type Preferences = {
  theme: "dark" | "light" | "system";
  timezone: "Asia/Tehran" | "UTC";
  notifications: boolean;
};
export const defaults: Preferences = {
  theme: "dark",
  timezone: "Asia/Tehran",
  notifications: true,
};
const preferencesSchema = z.object({
  theme: z.enum(["dark", "light", "system"]),
  timezone: z.enum(["Asia/Tehran", "UTC"]),
  notifications: z.boolean(),
});
export function readPreferences(): Preferences {
  try {
    return preferencesSchema.parse(
      JSON.parse(localStorage.getItem("infrapilot-preferences-v1") || "null"),
    );
  } catch {
    return { ...defaults };
  }
}
export function savePreferences(value: Preferences) {
  try {
    localStorage.setItem(
      "infrapilot-preferences-v1",
      JSON.stringify(preferencesSchema.parse(value)),
    );
    return true;
  } catch {
    return false;
  }
}
export function metric(value: number | null, unit: string) {
  return value === null
    ? "در دسترس نیست"
    : `${new Intl.NumberFormat("fa-IR").format(value)} ${unit}`;
}
