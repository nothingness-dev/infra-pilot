# InfraPilot web application

One shared React/TypeScript/Vite application implements the ten supplied Persian
RTL concepts plus a four-step Mock setup proposal wizard. It calls the existing Python Provider → Triage → Setup pipeline
through an explicit local **MOCK** adapter. It is runnable offline after installing
dependencies. REAL mode, infrastructure execution and conversational AI are
unavailable and visibly explained.

Verified baseline: `origin/main` / merged PR #25,
`1024c8253d25b735627656d1eefd54bea053462b`.

## Run the complete local application

PowerShell, from the repository root, with Python 3.11+ and Node 22.18/npm 10.9
(the versions used for this delivery):

```powershell
# If the repository's existing Python environment has not been prepared:
python -m venv .venv
.\.venv\Scripts\python.exe -B -m pip install -r requirements-mock.txt

npm --prefix apps/web ci
npm --prefix apps/web run build
.\.venv\Scripts\python.exe -B -m integration.ui_server --mock
```

Open **http://127.0.0.1:8787/**. One Python process serves the built UI and API;
deep-link refresh works. The required `--mock` flag cannot enable Real mode.
Stop the server with Ctrl+C. No Liara credential is needed or read. The existing
Python dependencies already include FastAPI, Pydantic and Uvicorn; this milestone
adds no Python dependency and leaves Provider's standard-library runtime intact.

For hot reload, leave the Python server running and use a second terminal:

```powershell
npm --prefix apps/web run dev
```

Open **http://127.0.0.1:4173/**. Vite proxies `/api` to loopback 8787, preserves Host
and uses same-origin cookies. Ports are fixed intentionally; a changed API port
also requires updating the development proxy. `vite preview` alone has no API.
Do not expose this mock server publicly; production authentication/ACLs are a
separate integration milestone.

## Routes and interactions

| Route | Page and supported interactions |
| --- | --- |
| `/` | Dashboard: consistent service/incident/current approval counts, unknown health, unavailable HTTP chart, diagnostic link, resource absence and recent actual report activity. |
| `/services` | Services: search, sort, pagination, selection and detail link over the actual one-service catalog. No pretend project/type inventory. |
| `/setup` | Four-step Mock proposal: technical brief, unverified domain guidance, form validation and blocked plan submission. Uses the existing Setup planner; saves a names-only proposal with idempotent retry in SQLite. No service, DNS or SSL changes. |
| `/services/MOCK-service` | Details: overview, metrics, deployments/releases and collected-data tabs. Null metrics and missing release bodies remain explicit. |
| `/incidents` | Four synthetic lifecycle scenarios; lifecycle and collection-error filters, search/sort/page and selected preview. No severity is invented from collection errors. |
| `/incidents/INC-024` | Details (also 023/022/021): actual evidence/hypotheses/actions, safe capability errors, missing data, approval audit, refresh and acknowledged separate demo request. |
| `/analysis?incident=INC-024` | Actual engine result; report/evidence selection and five evidence/review stages. No invented AI answer or timed progress. |
| `/approvals?selected=APR-…` | Actual gate/store lifecycle, current counts, historical records, canonical operation, expiry, audit and acknowledged approve/reject. Decisions never execute operations. |
| `/reports` | Diagnostic reports, audit and allowlisted export tabs; search/sort/page, UTC date range where applicable, original retained-report links and safe JSON download. |
| `/connections/liara` | Three-step Mock source/capability/service workflow; actual state reload; Real access remains unverified. Password field is disabled server-configuration guidance. |
| `/settings` | Dark/light/system, Tehran/UTC date presentation, local notification preference, save/reset, read-only connection and gate policy. Persian is the supported UI language. |

Source/service selectors offer only available data. A fixed one-service Mock
catalog is not expanded with artificial services to fill the designs. Backend
prose is displayed verbatim as escaped text, including English diagnosis text.
No external font/CDN or telemetry request is required.

## Data and security

See [the UI contract](../../integration/UI_CONTRACT.md) for the source inventory,
endpoint bodies, exact projection and security boundaries. `src/data.ts` provides
runtime Zod validation and inferred types. Shared backend schemas are unchanged.

Session initialization uses actual existing fixture flows. GET does not rerun
diagnosis or consume authorization. Refresh creates a new revision and makes old
approval controls historical. Requests/decisions use actual SQLite-backed gate
methods and server-owned independent identities. Browser-supplied roles, actors,
permissions and extra fields are rejected. No execution endpoint exists.

Only `infrapilot-preferences-v1` (theme, timezone, local notification boolean) is
persisted in localStorage. CSRF is module-memory only; session cookie is HttpOnly.
The Setup form keeps environment values only in component memory; it sends and
stores **names only**, including on retries. Validation messages never echo
values. Navigating away discards form values. Saved proposals appear separately
in Approvals with the exact target/ID, actual Setup planner step keys and missing
dependencies. They remain blocked because the Gate does not support
`setup_service`; those proposals have no approval/execute control. The wizard's
plans and hardware descriptions are Mock examples, not a Liara product catalog.
No Liara tokens, service environment, raw Provider response or raw log array is
sent to the browser. The diagnostic report can quote synthetic Mock log evidence.
Exports contain no diagnostic prose/log content or authentication information.

Unavailable/failed/skipped (`not_collected`) log collection has unknown received
count, while a truly empty collection has zero. Withheld text remains withheld,
not permanently discarded. `null` CPU/RAM/HTTP/observation time stays null; no
chart points, units, healthy defaults or current observation timestamps are made
up. API connectivity is separate from program health and latency.

## Structure and dependencies

- `src/App.tsx`: shared shell and ten routed page components; History API router.
- `src/Setup.tsx`: additional Mock setup wizard and safe proposal submission.
- `src/ui.tsx`: accessible tables, panels, dialogs, badges, timelines and navigation.
- `src/data.ts`: explicit read models, association checks, HTTP client, safe preferences.
- `src/styles.css`: shared semantic dark/light tokens and responsive RTL composition.
- `src/tests`: backend-generated synthetic projection, component and boundary tests.
- `public/assets/analysis-orb.png`: generated decorative bitmap, not a UI screenshot.
- `../../integration/ui_backend.py`, `ui_server.py`: narrow explicit-Mock bridge.
- `docs/screenshots`: actual local-browser captures; [verification record](docs/VERIFICATION.md).
- `worker`, `.openai`, `scripts/prepare-sites-build.mjs`: retained template packaging;
  no site ID, registration, sync or deployment. That static worker alone is not
  the Python-backed application.

React/ReactDOM render the interface; Zod validates JSON; Phosphor supplies icons;
locally bundled Vazirmatn supplies Persian text. Vite/TypeScript/Vitest/Testing
Library/jsdom are build/test tools. There is one committed `package-lock.json`.
See [third-party notices](THIRD_PARTY_NOTICES.md).

## Accessibility and themes

`lang=fa`, RTL DOM, isolated technical identifiers, semantic headings/landmarks,
non-color status labels, keyboard focus, skip link, polite status feedback and
native modal dialogs are included. The mobile drawer traps focus while open,
closes on Escape/navigation and returns focus to its trigger. Wide tables scroll
inside their own card; warnings/actions remain available on mobile. OS theme
changes are observed in system mode. Reduced motion disables spinner/drawer motion;
the decorative orb never claims an analysis job is running.

## Checks

```powershell
npm --prefix apps/web run typecheck
npm --prefix apps/web test
npm --prefix apps/web run build
npm --prefix apps/web run test:sites
.\.venv\Scripts\python.exe -B -m pytest -p no:cacheprovider -q
.\.venv\Scripts\python.exe -B -m unittest discover -s provider/tests -t . -v
```

Browser verification uses only loopback with real local bridge responses, not
the user's Liara account. See [design QA](design-qa.md) and the verification record
for viewports, screenshots, journey and remaining limits. This is a complete
readable offline interface, not evidence of production authorization, working
live Liara access, validated resource units or verified remediation.

The subsequent Setup integration and session-lifetime fixes are recorded in
[SETUP_VERIFICATION](docs/SETUP_VERIFICATION.md), with remaining live access,
production identity and executor requirements. A review server may use
`--port 8790`; use the handoff port rather than an older development process.
