# Executed verification — 2026-10-22

Runtime: Windows, Python **3.13.5**. Integration runtime/test source at
`5cbe243` (later commits add documentation, provenance and generated example).
Source revisions and all replayed dependency commits are in
[SOURCE_REVISIONS.json](SOURCE_REVISIONS.json).

Dependency profile: Pydantic 2.14.1, FastAPI 0.159.1, Starlette 1.9.0,
HTTPX 0.28.1, pytest 9.1.1, uvicorn 0.54.0. Full constraints are at repository
root. `python -m pip check` reported no broken requirements. A fresh resolver
initially selected newer FastAPI; it was replaced in the new isolated environment
with the previously reviewed 0.159.1 profile. No component dependency ranges were
changed or dependencies upgraded to silence warnings.

## Assembled checkout

Commands below use `.\.venv\Scripts\python.exe -B` as `python`:

| Command | Executed result |
| --- | --- |
| `python -m pytest -p no:cacheprovider -q` | 661 passed, no skips, one existing TestClient deprecation warning |
| `python -m unittest discover -s provider/tests -t . -v` | 119 passed |
| `python -m unittest discover -s setup/tests -t . -v` | 99 passed |
| `python -m pytest -p no:cacheprovider -q apps/liara/triage/tests` | 416 passed, one existing warning |
| `python -m unittest discover -s provider/qa -v` | 9 passed |
| `python -m unittest discover -s integration/tests -t . -v` | 18 passed |
| `python -B -S -m unittest discover -s provider/tests -t . -v` using base Python | 119 passed without site packages |

The aggregate 661 includes the component/QA/integration rows; these are not
additional disjoint totals. Pytest also reports 573 passing unittest subtests.
Every supported scenario was executed through a real CLI subprocess in the
integration suite: exported 0, empty 0, unavailable 1, not_collected 0,
withheld 0, partial_logs 0, partial_failure 1. Each emitted parseable JSON with
empty stderr and false authorization-consumption/execution flags. Invalid
arguments/opt-in returned 3 without canary echo; missing site-package dependencies
returned a safe 2. Tests also exercised interruption 130 and output failure 2.

The generated [partial-failure JSON](examples/partial_failure.json) is actual
current integrated output, not a handcrafted expected diagnosis. Pipeline spies
confirmed Provider collection, Triage diagnosis, Setup consumption and companion
attachment all execute; diagnosis executes exactly once per completed run.

## Existing historical compatibility tools

- `python setup/qa/run_collection_context_checks.py --suite all`: Setup 99,
  pinned Provider 119, Provider QA 9 and pinned Task 05A 350 all passed. Its existing
  TestClient deprecation and anyio assertion-rewrite warnings remain visible.
- Triage's source preparation succeeded in the current checkout after the narrow
  portability fix, verifying 35 Provider and 37 Setup pinned files. Its original
  `qa/test_collection_context_implementations.py` passed all 23 tests with the
  documented pinned PYTHONPATH and one existing TestClient warning.

These optional tools intentionally use original hash-verified source copies.
They are distinct from the normal-import runtime and 661 assembled-source tests.

## Fresh-source reproduction

A Git archive of tracked runtime/test commit `5cbe243` was extracted into an
ignored new directory, with no `.git`, virtual environment, egg metadata or QA
scratch sources copied in. A separate new virtual environment was created there.
The documented `pip install -r requirements-mock.txt` succeeded. Assertions
confirmed `integration`, `provider`, `setup` and `infrapilot_triage` all import
from that fresh source tree, not the original checkout or its QA copies.

All **661 tests passed again**, with the same single existing TestClient warning.
The actual partial-failure CLI emitted complete structured output and expected
exit 1. A further run outside the fresh checkout directory confirmed the
installed packages and Mock flow work through normal imports without cwd/sys.path
bootstrapping. This verifies source-only runtime operation without historical Git
objects; optional pinned QA still requires those objects as documented.

No live API, account/key, listener, infrastructure command, approval consumption,
production authentication, UI, merge, force-push or deployment was exercised.
Other Python versions and non-Windows platforms were not run for this delivery.
