# Read-only composition verification

Date: **2026-10-23**, Windows, Python **3.13.5**, existing root `.venv`.
This record follows the separate historical Mock, workflow and outcome records;
their pinned source revisions and verification results are unchanged.

## Verified baseline

- Clean starting branch: `feat/backend-outcome-evaluation` at `525f7c6`.
- `origin/main`: `e07c3e7ed1b5eb7a46a4edbb2234c2d8a1dea794`.
- GitHub PRs #16, #17 and #18 actually report `MERGED`; no assumed merge.
- PR #15 remains open against `feature/liara-collection-context`, containing
  Incident UI documentation only. It was not included, modified or merged.
- New branch: `feat/liara-readonly-backend-integration`, created from that main.
- The pre-change full suite passed **730 tests**, **683 subtests**, no skips,
  with the existing Starlette/HTTPX TestClient deprecation warning.

## Executed checks

```powershell
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q
python -B -m unittest discover -s provider/tests -t . -v
python -B -S -m unittest discover -s provider/tests -t . -q
```

Full suite: **765 passed**, **749 subtests passed**, no skips. The one existing
Starlette/HTTPX deprecation warning remains; dependencies were not upgraded to
hide it. Provider: **121 tests passed** with standard Python and again with
site-packages disabled. No other Python version/OS, clean-environment reinstall,
CI execution or authenticated network verification is claimed for this task.

The new integration module also passed directly under unittest:
`.\.venv\Scripts\python.exe -B -m unittest integration.tests.test_readonly -q`
(33 tests).

There are 33 new integration tests and two public Provider configuration tests.
They cover actual urllib-backed `LiaraClient` collection and the actual canonical
normalizer, retained producer, pure Diagnosis engine and Setup consumers. HTTP
responses are synthetic; sockets, subprocesses and approval/contextual entry
points are guarded in the in-process composition tests. Requests are asserted to
be GET-only, body-free and limited to the collector's three existing paths.
Separate CLI subprocess tests only use help, invalid opt-in, missing settings or
site-packages-disabled dependency failure, so none construct a network transport.

Coverage exercised includes:

- Missing opt-in and token/project/service/scope settings; invalid token, aliases,
  Unicode, base URL, timeout and log window; no client constructed on rejection.
- Successful collection with engine called exactly once, exact actual report
  association, original context and complete request fingerprint retained.
- Partial 401/403/404/429/500/502/503/504 failures, socket/URL timeouts, network
  errors, invalid JSON/nonfinite data and continued independent collection.
- Total collection failure with an honest unknown/incomplete diagnosis; complete
  and partial results remain distinguishable from later-stage runtime failure.
- Skipped, empty, unavailable, withheld and failed logs, including source entries
  without a message. Exported/partially exported live text is not an opt-in here;
  the existing default withholds it, and an exported reference is rejected.
- Mock/real, service/project/scope/request mismatches; changed snapshot/context,
  digest and even a recomputed digest cannot replace the original reference.
- Invalid/wrong-target/wrong-source/replaced reports, wrong companion, mutable
  report/request changes and failed preservation/association. Earlier valid
  objects survive later failures, including interruption during diagnosis.
- Safe stdout/JSON/stderr, settings/result/exception representations and logging,
  sensitive response/header/log/environment canaries, output-pipe failure,
  dependency failure, unexpected exceptions and interruption.
- Existing Mock, request/approval and outcome suites all run in the full suite;
  their explicit opt-ins, offline behavior and existing output contracts remain.

The actual new module was also exercised as a subprocess for `--help`, missing
opt-in, invalid secret-bearing arguments, missing settings, and missing optional
composition dependencies under `-S`. Expected exits were 0/3/3/3/2, with no raw
argument/exception echo or stderr. Successful mocked-transport, partial, total
failure and interruption CLI paths were exercised in-process with the same
`main` function and actual backend composition.

Three generated JSON examples use that actual composition with mocked urllib
responses: complete/skipped logs (0), complete/withheld logs (0), and partial
metrics timeout (1). They are wrapped with
`example_provenance=offline_mocked_urllib_transport_not_live_evidence` and
`live_verification_performed=false`. They are not captured API responses.

## Live verification status

Presence was checked in the **process environment only**, without printing
values. `LIARA_API_TOKEN`, `LIARA_PROJECT_NAME`, `LIARA_SERVICE_ID` and
`LIARA_PROVIDER_SCOPE` were all absent. **No authenticated live inspection ran.**
No private credential file, unrelated account or credential store was searched;
no token or test service was issued/provisioned. No real sample, verified account
mapping, permission matrix, CPU/RAM units, health or API-wide support is claimed.
Existing official API capability evidence was not changed by mocked execution.

## Change boundaries and remaining work

Changed files:

- Runtime: `integration/readonly.py`, `readonly_config.py`,
  `readonly_inspection.py`, `readonly_report.py`, `composition.py`, `service.py`.
- Tests: `integration/tests/test_readonly.py`, `provider/tests/test_environment.py`.
- Shared configuration: `provider/environment.py`, `provider/examples/live_smoke.py`.
- Documentation/examples: root `README.md`, `integration/README.md`,
  `integration/READONLY_INSPECTION.md`, `integration/READONLY_VERIFICATION.md`,
  `integration/examples/readonly_mocked_transport.json`.

Runtime/tests/documentation are concentrated in `integration/`. Narrow changes
outside it are the public stdlib `provider.environment` validator, reuse of it by
the existing smoke wrapper, two Provider tests, and the root README entry link.
This removes duplicate environment parsing without changing the old smoke
command's output/argument/transport behavior. Shared composition validation is
pure and reused by the existing Mock retained inspection validator; its producer
and Mock-only preview remain separate.

No Setup/Triage runtime, shared schema, dependency manifest, capability claims,
approval policy, privileged/default HTTP route or executor was changed. No
merge, force-push, branch deletion, deployment or infrastructure mutation occurred.
Trusted account/caller identity and ACLs, durable storage, freshness/replay rules,
live permission/units verification and any future operations are still separate
reviewed milestones. All execution/authorization-consumption/remediation flags
remain false, and the outcome evaluator remains Mock-only.
