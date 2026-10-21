# InfraPilot internal contract proposal

**These are internal DRAFT contracts. Team approval is required before final
integration. They are NOT official Liara API schemas.** No endpoint names,
permissions, raw API payload shapes, or action capabilities are asserted here.

## Proposed integration

```text
Raham's Liara adapter and observability
    -> ServiceSnapshot
    -> Setayesh's diagnosis (future task)
    -> DiagnosisReport containing Evidence, ranked DiagnosticHypothesis,
       and ActionProposal
    -> Fatima's UI and operations workflow
```

Raham owns collecting and normalizing actual observations. Setayesh owns diagnosis
and, in a later task, approval policy. Fatima owns presenting the report and the
operations workflow. This package defines only data contracts; constructing a
model makes no request, diagnosis, approval decision, or infrastructure change.

## Proposed field meanings

- `ServiceSnapshot.service_id`: opaque, nonempty internal service identifier.
  `status` is normalized to `unknown`, `healthy`, `degraded`, or `unhealthy`;
  these values do not claim to match Liara's native statuses. `data_source` is
  required and must be `real` or `mock`.
- Optional observations: `http_status` (integer 100–599), `cpu_usage_percent`
  (0–100), `ram_usage_mib` (nonnegative mebibytes), `response_time_ms`
  (nonnegative milliseconds), `logs`, and `timestamp`. Measurements must be
  finite numbers; numeric strings and booleans are rejected. Timestamps, when
  present, must include a timezone offset.
- An omitted or null measurement means unavailable. Zero is a measured value.
  `logs=None` means unavailable or not collected; `logs=[]` means collection
  returned no entries for the adapter's observation window. No missing value is
  replaced with a synthetic measurement or log entry.
- `LogEntry` preserves `message` verbatim, with optional aware `timestamp` and
  `level` (`unknown`, `trace`, `debug`, `info`, `warning`, `error`, `critical`).
  An unspecified level is `unknown`.
- `Evidence` has a unique report-local `evidence_id`, observation `kind`
  (`status`, `http`, `metric`, `log`), and human-readable `description`.
  The description must record observations the producer actually received.
- `DiagnosticHypothesis` has `hypothesis_id`, `explanation`, finite `confidence`
  in [0, 1], and supporting `evidence_ids`. References must resolve within the
  enclosing report. Empty references are representable; a future diagnosis
  producer must explain any lack of supporting observations in `limitations`.
  Confidence represents producer confidence, not an independently calibrated
  probability.
- `ActionProposal` has `action_id`, `title`, `description`, `risk_level`
  (`unknown`, `low`, `medium`, `high`), explicit boolean `requires_approval`,
  and `status`, which defaults to and currently only accepts `not_executed`.
  Identifiers label suggestions; they are not callable API operations.
  Risk and approval fields are supplied values: no policy derives them here.
  `requires_approval=False` does not authorize or trigger execution.
- `DiagnosisReport` contains `service_id`, `summary`, required `data_source`,
  observed `evidence`, `hypotheses` ordered by descending confidence (ties
  allowed), proposed `actions`, `missing_information`, and `limitations`.
  Lists default to empty independent collections. Duplicate evidence,
  hypothesis, or action identifiers within their respective lists, unresolved
  evidence references, and incorrect ranking are rejected, without sorting or
  fabricating entries.

All models reject unexpected fields. Validation applies on construction or
`model_validate` / `model_validate_json`; mutable instances and lists should be
revalidated at integration boundaries after any edits by passing a fresh dict
from `model_dump()` to `model_validate()`. Use `model_dump(mode="json")` or
`model_dump_json()` for transport, retaining nulls. Schema validation checks
structure and links, not truth or source provenance. A single report/snapshot
source cannot describe mixed mock/real observations; keep them separate pending
a team decision.

## Questions requiring team agreement

1. What adapter values map to normalized health states, and which identifier is
   stable across adapter, diagnosis, and UI? Missing HTTP data must remain null.
2. Does available CPU telemetry use a 0–100 scale or a multicore scale above 100?
   Which RAM units and response-time statistic/window are available? The adapter
   must convert known units, or leave unsupported observations null. Do not clamp
   out-of-range CPU data to fit this draft.
3. What log time window, ordering, truncation, timezone, and sanitization rules
   should the adapter use? This initial snapshot does not encode window,
   per-observation timestamps, raw metric values on Evidence, or truncation
   metadata; extend the draft by agreement if needed.
4. How should collection failures and partial availability be communicated to
   diagnosis beyond null values? The future report producer must populate missing
   information and limitations from available context; this package infers none.
5. Confirm confidence ranking and UI wording, including an empty hypothesis list
   when diagnosis lacks sufficient observations. Confirm how mock data is labeled.
6. Agree on risk classification and approval policy in a later task. Who supplies
   these fields before policy integration? No safe default is inferred here.
7. Agree on eventual action capabilities and an execution lifecycle before adding
   statuses beyond `not_executed`. Execution is outside this module's Task 1 scope.

Any collection limits, retention, schema versioning, and error envelopes remain
integration decisions. No teammate's module or shared repository is modified by
this proposal.
