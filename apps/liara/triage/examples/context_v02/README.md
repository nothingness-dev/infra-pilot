# Exact INTERNAL DRAFT v0.2 examples — MOCK preview only

`mock_partial_failure.request.json` embeds the exact sanitized PR #12
`partial_failure.json` snapshot/context plus proposed MOCK correlation references.
`mock_partial_failure.response.json` is actual serialized output of
`preview_mock_contextual_diagnosis(..., mock=True)` using the real existing engine.

The context preserves log HTTP 403 permission denial and metric HTTP 429 rate
limiting as separate capability records. Those are provider collection outcomes,
not observed application HTTP status. Application HTTP/CPU/RAM/latency remain null;
health remains unknown; logs are unavailable, not successfully collected empty.

No trusted mapping is fabricated: response trust, provenance, authorization and
execution flags are false. Correlation IDs/hashes are untrusted claims. No
contextual HTTP route exists, and these files are not live response captures.
Old `/internal/triage/diagnose` accepts only the snapshot and rejects this envelope.

See `../../COLLECTION_CONTEXT_V02_PROPOSAL.md` for the full matrix, semantics,
source revision, tests, and unresolved approvals/dependencies. No shared contract
has been approved and no Liara request or service action was performed.
