# InfraPilot triage: contracts and diagnosis

The module contains Pydantic v2 data contracts, a deterministic diagnosis engine,
and automated tests. Python 3.11+ is required. There are no Liara requests,
credentials, Approval Policy decisions, action execution, LLM integration,
server, or frontend.

These are **internal DRAFT contracts**, pending team approval. They are **NOT
official Liara API schemas**. See [CONTRACT_PROPOSAL.md](CONTRACT_PROPOSAL.md).

## Windows PowerShell setup and tests

Use the canonical project root `C:\git\shared\infra-pilot`.
The commands below select its module directly. No activation or execution-policy change is needed. The
temporary-directory settings keep pip build files inside this module as well.

```powershell
Set-Location -LiteralPath 'C:\git\shared\infra-pilot\apps\liara\triage'
py -3 -m venv .venv
$triageOriginalTemp = $env:TEMP
$triageOriginalTmp = $env:TMP
try {
    $triageTemp = New-Item -ItemType Directory -Force -Path .\.tmp
    $env:TEMP = $triageTemp.FullName
    $env:TMP = $triageTemp.FullName
    .\.venv\Scripts\python.exe -m pip install --disable-pip-version-check --no-cache-dir -r .\requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
} finally {
    $env:TEMP = $triageOriginalTemp
    $env:TMP = $triageOriginalTmp
}
.\.venv\Scripts\python.exe -m pytest
```

`py -3` must select Python 3.11 or newer. To select an installed Python 3.11
explicitly, replace the environment creation command with:

```powershell
py -3.11 -m venv .venv
```

For subsequent test runs from any directory:

```powershell
Set-Location -LiteralPath 'C:\git\shared\infra-pilot\apps\liara\triage'
.\.venv\Scripts\python.exe -m pytest
```

If the environment blocks pytest's optional cache directory, run the same suite
without caching:

```powershell
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider
```

## Using the contracts

After installation, imports work independently of the working directory:

```python
from infrapilot_triage import ServiceSnapshot

snapshot = ServiceSnapshot(
    service_id="example-service",
    status="unknown",
    data_source="mock",
)
assert snapshot.cpu_usage_percent is None
assert snapshot.logs is None
payload = snapshot.model_dump(mode="json")
restored = ServiceSnapshot.model_validate(payload)
```

The example is synthetic. `data_source="real"` is a producer declaration; schema
validation does not verify provenance. Preserve nullable fields during transport
to keep unavailable measurements distinct from zero and unavailable logs distinct
from an explicitly empty collection.

Dependencies use compatible major-version ranges rather than a lock file.
Installing them requires access to a Python package index or a pre-populated cache.
Do not copy `.venv`, `.tmp`, pytest caches, bytecode, or generated `*.egg-info` into
the teammates' shared repository.

## Diagnosing a snapshot

```python
from infrapilot_triage import DiagnosisThresholds, LogEntry, ServiceSnapshot, diagnose

# Synthetic example, not an observation of a real service.
snapshot = ServiceSnapshot(
    service_id="example-service",
    status="unhealthy",
    data_source="mock",
    http_status=500,
    logs=[LogEntry(message="PostgreSQL connection refused", level="error")],
)
report = diagnose(snapshot)
assert report.hypotheses[0].hypothesis_id == "database_connection_failure"
assert all(action.status == "not_executed" for action in report.actions)

# Optional local heuristic configuration; these are not provider limits.
report = diagnose(snapshot, thresholds=DiagnosisThresholds(high_cpu_percent=90))
```

See [DIAGNOSIS_ENGINE.md](DIAGNOSIS_ENGINE.md) for supported scenarios, ranking,
approval metadata, limitations, and the unchanged Task 1 contract boundary.
The full test command above runs the original 56 contract cases and all new
diagnostic tests. No API, workflow, or frontend integration is required to run it.
