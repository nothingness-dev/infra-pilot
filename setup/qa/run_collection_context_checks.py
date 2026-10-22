"""Offline QA only: read pinned producer trees without merging or runtime installs."""

import argparse
import importlib
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
PROVIDER_SHA = "66655e6f21b70717948122bc521b72f54b9d91a8"
TRIAGE_SHA = "d65f4b76ed44d32090a982c26af9b0a8a534d72d"


def copy_git_tree(ref: str, prefix: str, destination: Path) -> None:
    paths = subprocess.check_output(
        ["git", "-C", str(ROOT), "ls-tree", "-r", "--name-only", ref, prefix], text=True,
    ).splitlines()
    if not paths:
        raise RuntimeError("Pinned QA source is absent; fetch origin first.")
    for name in paths:
        relative = Path(name).relative_to(prefix)
        target = destination / relative
        if not target.resolve().is_relative_to(destination.resolve()):
            raise RuntimeError("Unexpected QA source path.")
        content = subprocess.check_output(["git", "-C", str(ROOT), "show", f"{ref}:{name}"])
        if target.exists() and target.read_bytes() != content:
            raise RuntimeError("QA destination differs; preserve it and select a new scratch directory.")
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("setup", "provider", "provider-qa", "triage", "all"), default="all")
    args = parser.parse_args()
    scratch = ROOT / "setup/.tmp/collection-context-qa-66655e6-d65f4b7"
    copy_git_tree(PROVIDER_SHA, "provider", scratch / "provider")
    copy_git_tree(TRIAGE_SHA, "apps/liara/triage", scratch / "apps/liara/triage")
    # Preload the actual producer packages before unittest adds the Setup root.
    # This is a QA bootstrap only; no production Setup file imports scratch paths.
    sys.path[:0] = [str(scratch), str(scratch / "apps/liara/triage/src"), str(ROOT)]
    for package in ("provider", "infrapilot_triage"):
        loaded = importlib.import_module(package)
        if not Path(loaded.__file__).resolve().is_relative_to(scratch.resolve()):
            raise RuntimeError("QA imported an unexpected producer package.")
    sys.path.insert(0, str(ROOT))
    print(f"Synthetic QA: Provider {PROVIDER_SHA}; Triage {TRIAGE_SHA}", flush=True)
    passed = True
    suites = {
        "setup": (ROOT / "setup/tests", ROOT),
        "provider": (scratch / "provider/tests", scratch),
        "provider-qa": (scratch / "provider/qa", None),
    }
    for name, (start, top) in suites.items():
        if args.suite not in ("all", name):
            continue
        print(f"Suite: {name}", flush=True)
        tests = unittest.TestLoader().discover(str(start), top_level_dir=str(top) if top else None)
        passed = unittest.TextTestRunner(verbosity=1).run(tests).wasSuccessful() and passed
    if args.suite in ("all", "triage"):
        import pytest
        passed = pytest.main(["-p", "no:cacheprovider", "-q", str(scratch / "apps/liara/triage/tests")]) == 0 and passed
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
