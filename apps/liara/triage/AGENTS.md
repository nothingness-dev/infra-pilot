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
- Do not merge any PR or start the API/real execution integration. Push only the
  current task's feature branch and preserve all existing dependency branches.
- Contracts are internal DRAFTS, require team approval before final integration,
  and are NOT official Liara API schemas.

Run tests from the canonical module:

```powershell
Set-Location -LiteralPath 'C:\git\shared\infra-pilot\apps\liara\triage'
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider
```

See `README.md` for module-local environment and dependency setup. Preserve
the existing contract and diagnosis functionality while developing Task 3.
