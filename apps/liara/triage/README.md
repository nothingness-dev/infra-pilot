# InfraPilot triage: Task 1

Setayesh's module currently contains Pydantic v2 data contracts and automated tests.
Python 3.11+ is required. There are no Liara requests, credentials, diagnosis
algorithms, approval decisions, action execution, server, or frontend.

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
