"""Explicit offline opt-in: python -B -m provider.examples.context_demo --mock."""

import json
import sys

from .context_fixtures import build_mock_context


def main(argv=None) -> int:
    # Fixed errors never echo unsupported arguments (which could contain secrets).
    if (sys.argv[1:] if argv is None else argv) != ["--mock"]:
        print(json.dumps({"error_code": "EXPLICIT_MOCK_REQUIRED"}))
        return 3
    print(json.dumps(build_mock_context().to_request(), indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
