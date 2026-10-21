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
  and tests. Do not start Task 2 without a separate explicit request. No diagnosis
  algorithm, Approval Policy, infrastructure execution, API server, frontend,
  Liara API calls, keys, or secrets belong in Task 1.
- Contracts are internal DRAFTS, require team approval before final integration,
  and are NOT official Liara API schemas.

Run tests from the canonical module:

```powershell
Set-Location -LiteralPath 'C:\git\shared\infra-pilot\apps\liara\triage'
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider
```

See `README.md` for module-local environment and dependency setup. Preserve
the existing Task 1 functionality during Git integration.
