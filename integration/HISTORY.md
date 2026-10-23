# Persistent inspection history

`infrapilot-inspection-history/1` adds a local SQLite history of **validated
inspection summaries**. It works offline and is independent of the unresolved
live account/service access check. No infrastructure action, identity backend,
approval mutation, executor or UI is enabled.

## Run the offline demo

Use the existing root environment; no dependencies were added. Keep the database
outside tracked source, in an operator-controlled directory. The existing ignored
`.tmp` is suitable for local development:

```powershell
New-Item -ItemType Directory -Path .tmp -Force | Out-Null
.\.venv\Scripts\python.exe -B -m integration.history_demo --mock --database .tmp/inspection-history.sqlite --scenario partial_failure
.\.venv\Scripts\python.exe -B -m integration.history_demo --mock --database .tmp/inspection-history.sqlite --list
```

The first command calls the actual Mock collector, Diagnosis engine and Setup
consumers, saves an allowlisted summary, closes the connection, and reads it back
through a new connection. The second command reads existing history without
collection or diagnosis. Neither command reads a Liara token or constructs a live
client. `--mock` is mandatory; no flag switches this command to live access.

Exit 0 means the local history operation succeeded, including when the archived
inspection had partial/failed collection. Capability errors remain in the record;
0 does not mean healthy, repaired or authorized. Exit 2 is a storage/dependency/
output failure, 3 is invalid arguments or missing opt-in, and 130 is interruption.
`--help` and opt-in rejection work without the composition dependencies installed.
Unknown arguments and raw exception messages are not echoed.

The JSON includes `history_only=true`, the saved record digest, up to 20 newest
summaries and their count. `returned_count` is this page's size, not a total across
all history. Repeating the same unchanged inspection is idempotent, retaining its
original sequence and storage time. Different existing Mock scenarios provide
additional records. The [generated example](examples/history_partial_failure.json)
is explicitly synthetic and is not live Liara evidence.

## Trusted Python interface

```python
from integration.history import SQLiteInspectionHistory
from integration.service import MockSession

inspection = MockSession(mock=True, scenario="partial_failure").inspect()
with SQLiteInspectionHistory(".tmp/inspection-history.sqlite") as history:
    saved = history.save(inspection)

# A process restart can open the existing file and retrieve historical data.
# Select the binding independently in trusted backend configuration.
with SQLiteInspectionHistory(".tmp/inspection-history.sqlite", create=False) as history:
    record = history.get(saved.record_id, expected_binding=inspection.source_binding)
    page = history.list_for(expected_binding=inspection.source_binding, limit=20)
    older = history.list_for(expected_binding=inspection.source_binding,
                             before_sequence=page[-1].sequence, limit=20)
    same_brief = history.list_for(expected_binding=inspection.source_binding,
                                  request=inspection.request)
```

`save` accepts only actual retained `CompletedInspection` or `ReadOnlyInspection`
objects. It revalidates the original producer, complete context, request and report
associations before projecting. To archive an actual read-only result, explicitly
call `history.save(inspection)` after the existing read-only composition; no live
command is changed to persist automatically. A valid earlier collection can be
archived after a later diagnosis/association failure. An inspection without a
valid retained collection cannot be recorded by inventing missing observations.

`get` and `list_for` require the expected backend-selected `ServiceBinding`.
Changing service, project, provider namespace or real/mock origin selects a
different partition. `request` filtering uses the full existing Setup request
fingerprint. Pages are newest-first, limit 1–100, with an optional exclusive
sequence cursor; retry-related sequence gaps are allowed. A missing scoped record
returns `None`. Invalid input, corruption or storage failure raises a fixed-code
`HistoryError`, with no input/path/SQL/secret reflection.

These Python ports remain trusted local composition. The binding is an
association check, not caller authentication or an ACL. Do not accept it from an
HTTP client as authorization.

## Stored information and privacy

The record stores only:

- Version, real/mock source and pipeline stage/error.
- Opaque digests of the complete binding, request ID and full request fingerprint.
- The original snapshot/context digests and a digest of the actual generated
  report, without rewriting or recreating the original producer envelope.
- Original capability availability, safe codes, HTTP status, retryability and
  collector instants; log disposition/counts; fixed limitation codes.
- Diagnosis aggregate counts, unknown application health and null unverified
  telemetry; explicit false provenance/freshness/authorization/execution flags.
- A local sequence and aware UTC `stored_at`, describing database storage only.

It stores no token/configuration, raw API response, log text, diagnostic prose,
environment variable, project/scope/raw service identifier, request ID, free-form
goal or full request details. Even reviewed Mock log text is reduced to its
counts/disposition; this does not alter the original retained Provider export.
Opaque hashes are correlation aids and can be guessable for predictable inputs;
they are not encryption or guaranteed anonymization. Use a private directory and
appropriate operating-system permissions. The SQLite database is not encrypted.

Missing data stays missing. Available logs with all text withheld, actually empty
logs, unavailable logs and skipped/failed collection stay distinguishable.
Collector/storage times are not source freshness or application latency. Error
403/404 does not become API-wide non-support.

## Storage guarantees and limits

SQLite transactions atomically insert each immutable summary. Content digests
deduplicate retries; no application update/delete operation is exposed. Different
connections serialize writes using SQLite locks and a bounded timeout (default
5 seconds). Use one store instance per thread; close it explicitly or use its
context manager. The database file and parent directory must be accessible to
the operator; parent directories are never created implicitly.

Application ID and schema version 1 are verified before use. Foreign databases
and unsupported versions are refused without overwriting or silently migrating
their data. `create=False` refuses a missing database. This version still uses a
read/write connection for schema verification, including listing. There is no
schema migration, backup/retention service or multi-host database implementation.

Records are bounded to 64 KiB of canonical finite ASCII JSON. Reads check shape,
canonical encoding, content digest, binding/request association and storage-time
format. Oversized/corrupted selected records cause an explicit error rather than
being returned or silently skipped. The digest covers the summary, not a signed
external provenance statement or tamper-proof storage clock. Anyone able to
rewrite the database and recompute its digests can forge historical data.

Retrieved `HistoricalInspection` values are detached historical DTOs. They cannot
be passed to `save` as new trusted inspections, reconstructed into
`PreparedCollection`, substituted for a current Setup companion, used to revive
an approval or fed into the Mock-only outcome evaluator as retained references.
The separate [local Mock request store](REQUESTS.md) now supports controlled-brief
completion/resume without changing this schema. Raw evidence/report persistence
and durable approval/audit storage remain separate work. Existing in-memory Approval behavior
and its production trust blockers remain unchanged.

See [verification](HISTORY_VERIFICATION.md) for executed checks and delivery scope.
