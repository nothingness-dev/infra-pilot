# Incident UI readiness and handoff

## Result

The shared frontend is **not present in the inspected published repository**.
The user explicitly requested a component contract when the shell is unavailable;
this task therefore delivers [COMPONENT_CONTRACT.md](COMPONENT_CONTRACT.md).
No rendered component, independent frontend, server, design system or new API
is implemented. Component tests, browser screenshots and a frontend build cannot
be truthfully produced without that foundation.

Canonical root: `C:\git\shared\infra-pilot`.
Branch: `feature/liara-incident-ui`, based directly on
`feature/liara-collection-context` at
`51d268d94757b5cc3d2f01bf04709aa71ee248b6`. PR #14 is open and remains unmerged.
Only the two documents inside `apps/liara/triage/incident/` belong to this change.
Existing source, tests, contracts, prior audit and examples remain unchanged.

## Inspection evidence

Remote references were fetched before inspection. All distinct fetched remote
commit trees were enumerated, including main, the latest Triage branch, Provider,
Setup's original application branches and Setup PRs #8/#9/#13. No tree contains
package.json, JavaScript/TypeScript components, HTML/CSS/Sass, Vue/Svelte sources,
frontend tooling, shared design tokens, or a frontend-specific ownership contract.
The active working tree was also inspected for local source/manifests.

| Inspected source | Revision | Actual finding |
| --- | --- | --- |
| origin/main | `cc20096285a34ffd5e8c622612b8804953216b37` | Python `provider/` and `setup/`; no frontend shell or build manifest |
| Triage / PR #14 | `51d268d94757b5cc3d2f01bf04709aa71ee248b6` | Python package, internal API, MOCK fixtures, contextual proposal; no browser UI |
| Setup compatibility / PR #8 | `a9d7482e0a1f67a396b5cd98609b217eeb13079f` | Python report presentation/API-response consumer |
| Setup approval / PR #9 | `929574dcde9e95e60c5a5889b5257612589c5a2c` | Python parent-workflow association and lifecycle transitions; no browser controls |
| Setup context / PR #13 | `7e559255a72134473aac75c1de0c42b21864b061` | Python companion retains context/report; unresolved production readiness |
| Provider proposal / PR #12 | `66655e6f21b70717948122bc521b72f54b9d91a8` | Draft context v0.2 and synthetic fixtures; not an approved shared contract |

Applicable instructions: `../AGENTS.md`; no ancestor/root instructions or nested
Incident instructions were found. Teammate files were inspected with `git show`,
not merged, checked out, edited or copied into this feature. Existing ignored
module-local QA source copies are from the prior task and were not modified here.

Read-only inspection commands (from the canonical root):

```powershell
git rev-parse --show-toplevel
git status --short --branch --untracked-files=all
git for-each-ref --format='%(refname) %(objectname)' refs/remotes/origin
git ls-tree -r --name-only origin/main
git ls-tree -r --name-only origin/feat/setup-collection-context
git show origin/feat/setup-collection-context:setup/triage.py
git show origin/feat/setup-collection-context:setup/diagnosis_api.py
git show origin/feat/setup-collection-context:setup/approval_workflow.py
git show origin/feat/setup-collection-context:setup/collection_context.py
```

The same recursive tree inspection was applied to every distinct fetched remote
revision, not just main. Browser framework, route/import location, tokens and
frontend build/test commands therefore remain unknown, rather than guessed.

## Exact missing integration requirements

| Requirement | Responsible owner | Needed before feature implementation |
| --- | --- | --- |
| Publish shared shell | Frontend/Setup owner | Branch/SHA, framework/version, app root, package manager/lockfile, routing, build and component-test commands |
| Agree feature ownership/import path | Frontend owner + Triage | Concrete frontend Incident directory, allowed imports/exports, mount point and scoped-style convention |
| Publish design/accessibility primitives | Frontend owner | Existing token names, semantic color/status/risk roles, Persian font, RTL layout, buttons/cards/alerts, breakpoints and focus conventions |
| Approve component boundary | Setup + Triage | Props/callback and incident revision convention in COMPONENT_CONTRACT.md; no report/schema replacement |
| Provide associated data | Setup/composition | Sanitized snapshot + exact report for current service/request/revision; no frontend-generated trusted evidence |
| Provide parent review/status flow | Setup/composition | Server-backed scoped review permissions, association checks, safe unavailable/error handling and a non-consuming status refresh mechanism |
| Agree contextual display input | Provider + Setup + Triage | Approve draft versions, full context retention, capability authority, withholding/retention semantics and companion freshness rules |
| Define privileged trust integration | Backend owners | Authentication/ACLs, durable stores and trusted canonical action mapping; these remain outside this UI task |

The future feature may be implemented with review controls unavailable while
backend dependencies remain absent, but only once the shell and component/ownership
boundary are agreed. Do not make frontend development depend on enabling real
infrastructure execution or merging PR #14. No live operation is in scope.

## Existing fixtures and component acceptance checklist

Paths below are relative to `apps/liara/triage/`. Use these actual serialized
payloads; do not replace them with handcrafted diagnosis results or service metrics.

| Scenario | Actual source / future test input | Required assertion |
| --- | --- | --- |
| Diagnosis, hypotheses and evidence | `examples/mock_db_http500.request.json` and `.response.json` | Summary, producer ranking, confidence and exact evidence references render; sensitive recommendation stays not_executed |
| Measured CPU/latency | `examples/mock_cpu_latency.request.json` and `.response.json` | Show only actual supplied values/units; no inferred memory limit |
| Healthy with incomplete telemetry | `examples/mock_healthy_incomplete.request.json` and `.response.json` | Healthy is not complete observability; nulls/limitations and MOCK label remain visible |
| Status unavailable | A valid report with no associated snapshot prop | Show unavailable status/time; never infer current health from report text |
| Contextual partial failures | `examples/context_v02/mock_partial_failure.request.json` and `.response.json` | Preserve simultaneous logs 403/metrics 429, unknown health, null metrics and MOCK-only trust limitations |
| Empty, withheld and partial logs | Exact `tests/fixtures/provider_context_v02/{empty,withheld,partial_logs,unavailable,not_collected}.json` | Distinguish []/null, count accounting and incomplete exports; never claim withheld is permanently discarded |
| Sensitive action pending | `examples/mock_sensitive_pending.response.json` | Pending lifecycle from actual serialized GateDecision; not authorized or executed; this standalone gate fixture has no Setup proposal/report binding, so it must not enable review controls |
| Authorization denied | `examples/mock_authorization_denied.response.json` | `unauthenticated` denial, distinct from rejection and from default HTTP 503; no execution-success message |
| Approved/rejected/expired/consumed lifecycle | Future parent adapter fixtures serialized from existing real offline gate transitions; do not invent results | Each state shown independently of authorization; approve/reject/consume never imply service execution |
| Approved without execution | Existing `infrapilot_triage.demo.run_mock_demo(mock=True)` output, offline only | Approved and authorized_not_executed remain MOCK and never become remediation success |
| Resource states | Component-only loading/empty/error props from the proposed contract | Accessible Persian copy, no stale review controls, no raw errors |
| Invalid association/data | Explicitly mutated copies of existing fixtures | Unknown enums, bad evidence/ranking, source/service/context mismatch or stale revisions disable review and show safe invalid data |
| No hidden privilege calls | Future component network/callback spies | Review signals parent intent only; no direct authorize/policy/approve/restart call or local approval persistence |
| RTL and accessibility | Future shell's component/browser runner | Keyboard evidence links, mixed-direction identifiers, focus, semantic status labels, responsive reading order |

The pending and denied fixtures are serialized gate examples, not browser endpoints
or interchangeable Setup updates. Their request IDs and historical mock timestamps
are not live approval credentials. There are no stored rejected/expired Setup JSON
fixtures in this branch; the future component tests must obtain legitimate offline
transition output through the existing gate/parent adapters after the shell exists.

## Verification and publication

No component tests or frontend build command exist in the inspected repository.
No JavaScript package, test runner or dependency is introduced for this proposal.
Existing Python regression checks remain applicable and do not prove UI rendering.

From the canonical module, using the existing environments:

```powershell
Set-Location -LiteralPath 'C:\git\shared\infra-pilot\apps\liara\triage'
$env:PYTHONDONTWRITEBYTECODE = '1'
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider
.\.tmp\qa-py312\Scripts\python.exe -m pytest -p no:cacheprovider
```

Verified after adding this proposal:

| Existing suite | Actual result |
| --- | --- |
| Python 3.14.7 | 416 passed, 1 warning in 5.54s |
| Python 3.12.13 | 416 passed, 1 warning in 5.70s |

The 416 tests comprise all 350 earlier regressions plus 66 collection-context
cases. The warning is the existing Starlette HTTPX TestClient deprecation;
dependencies were not upgraded and the warning was not suppressed. These checks
validate existing backend behavior only, not the proposed component's rendering.

Publish only `feature/liara-incident-ui`, with a stacked proposal PR targeting
the still-open `feature/liara-collection-context` dependency. The title/description
must clearly state that this is a component-contract fallback, with frontend
implementation blocked, rather than claiming a working Incident UI. Do not merge
any PR, modify teammate branches, or start another task.
