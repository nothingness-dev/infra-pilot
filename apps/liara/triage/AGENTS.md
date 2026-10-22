# InfraPilot triage workspace rules

- The ONLY InfraPilot project root is `C:\git\shared\infra-pilot`.
- Setayesh's module is `C:\git\shared\infra-pilot\apps\liara\triage`.
- Run repository-level Git commands from the canonical project root and module
  development commands from this module or one of its descendants. Verify the
  working directory and use explicit absolute working directories with tools.
- Confine Setayesh's development, environments, temporary build files, and test
  artifacts to this module. Do not modify teammates' modules or unrelated files.
- Never create or modify InfraPilot files under `E:\courses\alghoritm` again.
  The old Task 1 copies are retained originals; do not edit or delete them.
- Run Git only when explicitly authorized by the current user task. Use
  feature-based or module-based branch names and commit messages without
  personal names. Do not force-push, modify teammates' branches, or push to main.
- During Git integration, stage only explicitly approved module paths. Never
  use broad staging commands or include generated files, secrets, or others' work.
- Inspect existing destination files before transfers. Never overwrite conflicts
  blindly. Stop and report permission failures or content conflicts that prevent
  safe migration. Do not delete existing source files.
- Do not transfer `.venv`, `__pycache__`, `.pytest_cache`, `.tmp`, `*.egg-info`,
  or other generated artifacts between workspaces. Create a fresh local virtual
  environment when needed.
- Task 1 consists only of draft schemas, validation, packaging, documentation,
  and tests. Task 2 explicitly authorizes deterministic symptom extraction,
  evidence-based diagnosis, report generation, recommendations, and tests.
- Preserve the six Task 1 schemas and all existing tests. Document proposed
  contract extensions separately; do not silently change adapter/UI interfaces.
- Task 3 explicitly authorizes independent action classification, approval state
  management, a fail-closed authorization gate, structured audits, and tests.
  Use feature/liara-approval-policy based on the intact diagnosis branch.
- Keep shared schemas and the original 130 tests unchanged. Agent-provided risk
  and approval flags never grant authorization. Authentication and target ACLs
  must come from a trusted integration boundary, never a caller-supplied actor ID.
- No infrastructure execution, real authentication integration, LLM integration,
  API server, frontend, Liara API calls, keys, or secrets belong in Task 3.
- Task 4 explicitly authorizes a module-local FastAPI application and thin
  integration adapters on `feature/liara-triage-api`, based on Task 3. Preserve
  all existing core models, engine, gate, and the original 238 tests.
- Task 4 HTTP approval operations must be disabled by default. Install identity,
  authorization, policy, audit, and storage only through trusted server code;
  never accept caller-supplied IDs/roles as identity. Expose no approval mutations
  or execution routes. Mock fixture generation must be explicit and offline.
- No infrastructure execution, real authentication integration, provider calls,
  secrets, LLM, database, frontend, or Task 5 development belongs in Task 4.
- Task 05A explicitly authorizes integration/security QA, narrow verified fixes,
  a reproducible offline MOCK demo, and integration handoff documentation on
  `feature/liara-triage-qa-demo`, based on the intact Task 4 branch. Preserve all
  313 previous tests and all draft shared schemas. Do not start cross-module
  integration or another task. Inspect other owners' published code read-only.
- The demo must require explicit MOCK opt-in, use an isolated in-process app,
  install only opaque mock sessions with scoped permissions, and open no network
  listener. Never export its mock app as an ASGI server or modify the default
  application's disabled approval routes. No real Liara connection or execution
  may be claimed. Mock approval is not a real remediation result.
- Task 05B collection-context work is authorized on
  `feature/liara-collection-context` from the intact Task 05A implementation.
  Preserve the previous audit report byte-for-byte. Provider PR #12 remains a
  proposal; add only local structural validation, offline fixtures/tests, an
  explicit MOCK preview, and a reviewed draft contextual contract.
- Do not install a contextual HTTP route, real mapping/authentication, approval
  mutation or execution path without explicit contract/trust approval. Public
  IDs/hashes cannot authenticate correlation. Keep existing shared schemas,
  `/internal/triage/diagnose`, core behavior, dependencies and all 350 tests intact.
- Provider/Setup implementation copies for optional QA must be exact pinned Git
  blobs under this module's ignored `.tmp`, verified by hashes, with no edits to
  teammate files. Imported MOCK mappings must remain visibly fixture-only.
- Do not merge any PR. Push only the current task's feature branch and preserve
  all existing dependency branches and teammates' branches.
- Contracts are internal DRAFTS, require team approval before final integration,
  and are NOT official Liara API schemas.

Run tests from the canonical module:

```powershell
Set-Location -LiteralPath 'C:\git\shared\infra-pilot\apps\liara\triage'
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider
```

See `README.md` for module-local environment and dependency setup. Preserve
the existing contract, diagnosis, approval, and HTTP functionality while developing
Task 05B. See `COLLECTION_CONTEXT_V02_PROPOSAL.md` for the current proposal and
trust limits; earlier handoff/audit documents retain their pinned historical scope.
