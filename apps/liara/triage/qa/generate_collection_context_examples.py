"""Generate MOCK-only proposal examples from verified Provider PR #12 fixtures."""
import argparse
import hashlib
import json
from pathlib import Path

from infrapilot_triage.collection_context import context_digest, preview_mock_contextual_diagnosis


def main() -> None:
    parser = argparse.ArgumentParser(description="Offline contextual contract examples; no endpoint or trusted mapping enabled.")
    parser.add_argument("--mock", action="store_true", required=True)
    parser.parse_args()
    module = Path(__file__).resolve().parents[1]
    fixtures = module / "tests/fixtures/provider_context_v02"
    manifest = json.loads((fixtures / "SOURCE.json").read_text(encoding="utf-8"))
    data = (fixtures / "partial_failure.json").read_bytes()
    if hashlib.sha256(data).hexdigest() != manifest["fixtures"]["partial_failure.json"]["sha256"]:
        raise RuntimeError("Fixture hash mismatch")
    request = json.loads(data)
    request["correlation"] = {
        "service_id": request["snapshot"]["service_id"], "service_binding_ref": "MOCK-binding-1",
        "collection_ref": "MOCK-collection-partial-failure",
        "snapshot_digest": request["collection_context"]["snapshot_digest"],
        "collection_context_digest": context_digest(request["collection_context"]),
    }
    response = preview_mock_contextual_diagnosis(request, mock=True).model_dump(mode="json")
    directory = module / "examples/context_v02"
    directory.mkdir(parents=True, exist_ok=True)
    for filename, payload in (("mock_partial_failure.request.json", request), ("mock_partial_failure.response.json", response)):
        target = directory / filename
        data = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
        if target.exists() and target.read_bytes() != data:
            raise RuntimeError("Example differs; review before replacement")
        if not target.exists():
            with target.open("xb") as output:
                output.write(data)
        print(filename)


if __name__ == "__main__":
    main()
