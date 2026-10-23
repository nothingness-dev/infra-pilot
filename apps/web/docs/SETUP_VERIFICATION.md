# Mock Setup integration verification

Date: 2026-10-23. Windows, Python 3.13.5, Node 22.18.0. This follows the
ten-page delivery described in [VERIFICATION](VERIFICATION.md); its note that
parallel Setup was excluded is historical. This milestone reviews and includes
that work, corrects its behavior and adds regression coverage.

## Delivered behavior

- `/setup` adds four steps: brief, domain guidance, validation and proposal review.
  Frontend and backend agree on domain-label syntax, environment-name uniqueness,
  limits and supported **Mock** templates. SSL remains unverified and the UI gives
  no invented DNS target, runtime support or live resource/pricing guarantee.
- The server reuses `setup.workflow.prepare_request` and actual `ActionPolicy`.
  The persisted proposal contains actual Setup step keys and missing dependencies.
  `setup_service` remains unsupported; proposals stay blocked, never executable.
- Only environment variable **names** enter HTTP or SQLite. Values stay in form
  memory, never validation errors, logs, browser storage or the saved response.
- UUID4 idempotency binds canonical brief contents within the existing session.
  Retry returns the saved record; changed content with the same key returns 409.
  Maximum 100 proposals, 4096-byte request and bounded retained-record reads.
  Corrupt/unknown fields fail closed with a fixed error instead of raw contents.
- The worklist preserves the exact target/ID, apart from separate restart reviews.
  No setup approval or execute button is offered. GET does not collect provider
  data or infer authentication from stored metadata.
- Failed/ambiguous requests retain the form and retry key; repeated in-flight
  clicks submit once. A mutation never silently reboots into a new session.
  A valid-looking response for a different target is rejected. A late response
  cannot navigate after the form has unmounted.
- Session lifetime is enforced server-side using a monotonic deadline, independent
  of the cookie. Bootstrap does not extend it. Expired sessions release capacity
  and close their operators; a periodic reaper also cleans idle expired sessions.
  Active sessions retain their identity/CSRF. Audit projection is request-scoped.

## Executed checks

| Check | Result |
| --- | --- |
| Complete Python pytest suite | **1004 passed, 830 subtests passed** |
| Focused UI backend tests after final bounded-read change | **25 passed, 3 subtests passed** |
| Provider standard-library unittest suite | **136 passed** |
| Frontend component/boundary suite | **50 passed** |
| Strict TypeScript and production build | Passed |
| Static worker packaging suite | **4 passed**; no deployment |
| Browser | Actual loopback Setup submission, validation and persisted worklist after reload; desktop dark/light and 390px mobile inspected |

The existing Starlette/httpx deprecation and two Zod annotation warnings remain;
they did not fail checks. All checks are offline/Mock. No Liara request or
infrastructure change was made. The review server uses
`python -B -m integration.ui_server --mock --port 8790 --data-directory .tmp/ui-setup-review`.

Browser journey: enter `reviewed-mock-demo`, reject `bad..example.com`, correct
to the synthetic `app.example.com`, submit, inspect `SETUP-...` and the unchanged
blocked/false execution state, then reload and verify the same proposal remains.
The form and saved-worklist screenshots are under `screenshots/setup-*.png`.
No console errors were captured. Mobile document width stayed inside 390px.
Unit tests additionally exercise secret canaries, corrupt storage, canonical
retry/conflict, capacity, expiry, policy changes and stale component responses.

## Git integration

Base commits include UI `3f46107` and bridge `58d55bb`. At delivery, origin/main
was `990d9b2` (merged #26). GitHub reported #27 merged into
`feat/mock-ui-bridge`, **not main**. Therefore this follow-up PR targets main and
includes the UI commits as well as Setup, avoiding another retargeting dependency.
No merge, force push or deployment was performed by the agent.

## Remaining external integration

`LIARA_API_TOKEN` and `LIARA_PROJECT_NAME` were absent from the current process
environment. Live verification was therefore **not run**. Existing safe tooling
is documented in [READONLY_INSPECTION](../../../integration/READONLY_INSPECTION.md)
and [LIVE_VERIFICATION](../../../integration/LIVE_VERIFICATION.md). A configured
token must list the exact target before any live result can be treated as verified;
the prior zero-visible-project diagnostic is not resolved by Mock UI work.

The UI's local session boundary is not production login or a service ACL.
Connecting an actual identity provider/resolver and binding users to service
permissions remains separate integration work requiring a selected deployment
and trusted identity source. Browser-supplied roles cannot substitute for that.

No infrastructure executor or write endpoint is introduced. Enabling one still
requires verified provider write capabilities plus independent authorization,
action binding, expiry/replay protection and post-action verification. This
delivery does not bypass existing unsupported-operation policy to make a demo
look executable. A complete offline demonstration is ready; production readiness
and authenticated live operation remain unverified.
