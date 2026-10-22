# Setup collection_context compatibility — proposal, execution disabled

## Reviewed sources and preliminary verdict

Provider PR #12 head/prefix `66655e6` resolves exactly to
`66655e6f21b70717948122bc521b72f54b9d91a8`. The reviewed contract identifier is
`provider-collection-context/0.2-draft`, an internal proposal, not an approved
shared contract or live integration. Read its actual COLLECTION_CONTEXT_DRAFT.md,
collection_context.py, seven context_v02 fixtures and provider/qa tests.

Setup base: `929574dcde9e95e60c5a5889b5257612589c5a2c` (draft PR #9), containing
PR #8 at `a9d7482e0a1f67a396b5cd98609b217eeb13079f`. The topic
`feat/setup-collection-context` depends on PR #9 and does not merge producer
history. Main was fetched at `cc20096285a34ffd5e8c622612b8804953216b37`; PRs #8/#9
remain open drafts. No state in another repository was changed.

Triage QA reference: PR #11 at `d65f4b76ed44d32090a982c26af9b0a8a534d72d`.
Its escaped-quote redaction fix is used by Provider's own QA. Setup's older
published API ancestry lacks that fix; it is not silently patched here.

Preliminary verdict: the seven synthetic producer envelopes can be preserved
alongside existing Setup evidence/Diagnosis with a separate backend-owned
association, provided the actual sanitizer leaves the producer-digested export
unchanged. The envelope cannot be sent to the current Diagnosis endpoint (422);
only its unchanged snapshot is an endpoint input. Production approval, source
authenticity, freshness and shared-contract agreement remain unresolved.

## Field and semantics mapping assessed before implementation

| Concern | Actual Provider fields/semantics | Existing / proposed Setup boundary |
| --- | --- | --- |
| Request identity | No Setup request ID, operation or brief fingerprint | Existing SnapshotEvidence.association must come from backend orchestration and pass the full current request fingerprint checks. The new companion adds a Setup association; it does not pretend Provider supplied it. |
| Service identity | Exported service_id and private ServiceBinding(service_id, project_name, provider_scope, is_mock) | Require the actual retained PreparedCollection and independently resolved backend ServiceBinding. Exact snapshot/brief/service/source matching; no frontend registry selection. Project/scope are not UI props. |
| Snapshot | No snapshot UUID. snapshot_digest is SHA-256 of canonical exported snapshot, after the trusted log policy | Check that digest on the exact displayed snapshot. Retain existing DiagnosisPresentation.binding semantics unchanged; a new companion digest has a separate domain and includes the context. |
| Source / mode | data_source is mock or real; binding has is_mock | Match existing Setup mock/external provenance to snapshot mock/real. A real label is only a source claim, not authenticated live evidence or readiness. |
| Time | Nullable aware collection_started_at / collection_finished_at and per-capability collected_at | Preserve exactly as collector instants. snapshot.timestamp remains source measurement time (often null). No fabricated time, freshness TTL or shared observation window. |
| Outcomes | Ordered service/deployment/logs/metrics capability records: availability, error_code, http_status, collected_at, retryable | Preserve records; derive display errors from them. Partial failures retain surviving snapshot/context evidence. Retry hints never trigger a call. |
| Log disposition | log_export state and received/exported/withheld counts | Empty [] is distinct from unavailable, skipped, denied/failed and deliberately withheld null logs. Preserve partial exported messages and withheld counts. Reserved/unknown outcomes must remain distinguishable. |
| Sanitization | Trusted app-specific log callback; configured token removed before/after callback; nonempty text withheld by default. No exported sanitizer/policy revision or redaction receipt | Reuse Triage sanitize_snapshot before a new association. If it changes the digest-covered representation, block rather than recompute/relabel Provider's hash. Pattern redaction is not a general secret detector or a replacement team policy. |

The companion structure, digest, lifecycle and Incident UI interface below are
Setup proposals. No fields are added to ServiceSnapshot or DiagnosisReport.

## Reproducible synthetic QA

Use the existing Setup-owned Python environment and producer dependency ranges;
no editable producer install, root config or teammate source changes are needed.

```powershell
# From this topic's repository root; fetch pinned Git objects first if needed.
C:/Users/FATIMA/GitHub/infra-pilot/setup/.venv/Scripts/python.exe -B setup/qa/run_collection_context_checks.py --suite all
```

The QA-only runner reads pinned Git objects into ignored `setup/.tmp/` and
preloads the actual Provider/Triage packages before discovering this Setup tree.
It refuses to overwrite different scratch content. Production code must use
normal package imports, never these paths. `--suite setup`, `provider`,
`provider-qa` or `triage` can select individual checks. The original fixtures are
read without editing them. These are fixture/contract checks, not real API,
authentication, authorization or infrastructure integration.
