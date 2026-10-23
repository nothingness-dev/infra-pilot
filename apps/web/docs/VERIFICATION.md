# Verification record

Baseline: merged PR #25 / `1024c8253d25b735627656d1eefd54bea053462b`.
`origin/main` was fetched and verified at that baseline before delivery.
Date: 2026-10-23. Python 3.13.5, Node 22.18.0, npm 10.9.3, Windows.

| Check | Result |
| --- | --- |
| `npm run typecheck` | Passed, strict TypeScript with unused-variable/parameter checks |
| `npm test` | **41 passed**, 3 test files |
| `npm run build` | Passed, compiled client and retained static packaging |
| `npm run test:sites` | **4 passed**; static worker/packaging checks only, no deployment |
| `python -B -m pytest -p no:cacheprovider -q` | **993 passed, 830 subtests passed**; repeated in isolated delivery checkout |
| `python -B -m unittest discover -s provider/tests -t . -v` | **136 passed**, offline |
| New bridge tests within the full suite | **14 passed**, 3 parameterized subtests |
| Browser | 10 routes × 2 desktop themes, representative tablet/mobile, actual loopback-backed journey and safe download passed |

The Python suite has one pre-existing Starlette/httpx deprecation warning. The
build reports two Zod comment-annotation warnings; Rollup removes those comments
and the build succeeds. No live tests or deployment checks were performed.

## What the tests cover

Frontend tests verify all ten routes, safe invalid/backend failure states,
dark/light/system preferences and storage allowlisting, zero versus null,
capability/record/approval association, producer ordering, log accounting states,
export allowlists, escaped text, stale unmounted responses, deduplicated bootstrap
and expired-session retry, responsive menu state, search/page/selection and
sorting, health filters, exact evidence navigation, dialog cancellation,
acknowledged decision and disabled expired approval.

Bridge tests run the actual existing Mock pipeline, retained-object validation,
Approval Gate, inspection history and SQLite audit. They verify false execution
flags, separate sessions/identities, idempotent initialization, non-collecting
GET, CSRF/Origin/Host and body boundaries, rejection of forged actor/role fields,
expiry, final decision protection, stale revisions, safe errors, export allowlist,
bounded sessions, static SPA fallback and traversal rejection. They need no
external API or network listener.

## Browser journey and reproduction

Start the application as described in [README](../README.md). The delivered
checkout was additionally tested on local port 8788 using `--mock --port 8788`,
without changing an existing parallel development server.

1. Open Incidents, select active lifecycle and search `INC-024`; only its row
   and preview remain. Open detail and then its actual analysis/evidence link.
2. Return to the incident, open its associated request. Approve opens a native
   dialog. The submit control is disabled until review acknowledgement.
3. Submit. Wait for backend response and reload: stored state becomes approved,
   current pending count becomes zero, and **not executed / no execution grant**
   remains visible. Buttons are no longer actionable; incident stays active.
4. Open Reports → Audit: both request and granted-decision events appear with
   the same public request/incident association.
5. Open Exports and download its JSON. Confirm `source=mock`, `historical=true`,
   the documented allowlisted keys, and false consumed/authorized/executed flags.
6. Mobile: open drawer, navigate, filter/search, inspect detail and perform the
   acknowledged review; drawer closes on navigation. Tablet panels remain
   readable; tables scroll inside their own card.
7. Connection: continue through Mock capability results and service selection.
   REAL stays unavailable and never becomes connected by clicking a control.

These steps were exercised through the browser automation API against the real
local adapter, not a mocked fetch handler. Component tests separately use mocked
HTTP for deterministic CI. Browser evidence is committed under `screenshots/`;
the recorded journey is a verification artifact, not a Playwright CLI suite.

## Remaining scope

No live Liara account, token, HTTP probe, infrastructure mutation, executor or
production identity integration was used. Actual resource units/time-series and
release/deployment payloads are not provided by the UI projection. The seeded
Mock data has no ranked hypotheses; separate synthetic test inputs verify the
rendering and exact evidence links when a valid ranked hypothesis is supplied.

Parallel `Setup.tsx` navigation/styles added in the original checkout during the
interruption were preserved and excluded from this ten-page delivery. Validation,
screenshots and commits were completed from an isolated checkout containing only
this milestone. That parallel wizard needs its own reviewed integration scope.
