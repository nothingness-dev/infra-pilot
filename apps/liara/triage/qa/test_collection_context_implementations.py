"""Actual pinned Provider/Setup tests, separate from fixture-only triage tests."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import socket

from fastapi.testclient import TestClient
import pytest

import provider
import setup
from provider import CollectionContextAdapter, CollectionContextError, MockLiaraClient
from provider.examples.context_fixtures import MOCK_CONTEXT_SCENARIOS, build_mock_context, mock_context_binding
from setup.collection_context import preserve_collection_context, consume_collection_diagnosis_response
from setup.tests.triage_fixtures import problem, service_evidence
from infrapilot_triage.api import create_app
from infrapilot_triage.collection_context import (
    ContextCompatibilityError, context_digest, diagnose_contextual_request,
    preview_mock_contextual_diagnosis, validate_contextual_request, validate_provider_context,
)

MODULE = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session", autouse=True)
def verify_real_sources():
    directory = MODULE / ".tmp/collection_context_sources"
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    for package, imported, revision in (("provider", provider, "66655e6f21b70717948122bc521b72f54b9d91a8"),
                                         ("setup", setup, "7e559255a72134473aac75c1de0c42b21864b061")):
        root = directory / f"{package}-{revision[:7]}"
        assert Path(imported.__file__).resolve() == (root / package / "__init__.py").resolve()
        assert manifest[package]["revision"] == revision
        for filename, digest in manifest[package]["files"].items():
            assert hashlib.sha256((root / filename).read_bytes()).hexdigest() == digest


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("QA forbids external connections")
    monkeypatch.setattr(socket, "create_connection", forbidden)


def proposed(envelope):
    value = json.loads(json.dumps(envelope))
    context = value["collection_context"]
    value["correlation"] = {
        "service_id": value["snapshot"]["service_id"], "service_binding_ref": "MOCK-binding-1",
        "collection_ref": "MOCK-collection-1", "snapshot_digest": context["snapshot_digest"],
        "collection_context_digest": context_digest(context),
    }
    return value


@pytest.mark.parametrize("name", MOCK_CONTEXT_SCENARIOS)
def test_actual_producer_matches_pinned_fixtures(name):
    retained = build_mock_context(name)
    envelope = retained.to_request()
    fixture = json.loads((MODULE / f"tests/fixtures/provider_context_v02/{name}.json").read_text(encoding="utf-8"))
    assert envelope == fixture
    assert retained.verify_request(envelope, expected_binding=mock_context_binding()) == envelope
    assert validate_provider_context(envelope).model_dump(mode="json") == envelope


@pytest.mark.parametrize("status,availability", [(403, "permission_denied"), (404, "not_found")])
def test_actual_provider_http_outcomes_are_preserved(status, availability):
    binding = mock_context_binding()  # Provider's own explicitly synthetic mapping.
    result = CollectionContextAdapter(MockLiaraClient(failure_modes={"logs": status}),
                                      provider_scope=binding.provider_scope).collect(binding, logs_since="MOCK-window")
    envelope = result.data.to_request()
    context = validate_provider_context(envelope).collection_context
    failure = next(item for item in context.collection_errors if item.capability == "logs")
    assert failure.http_status == status and failure.availability == availability
    preview = preview_mock_contextual_diagnosis(proposed(envelope), mock=True)
    assert preview.collection_context.capabilities[2].http_status == status
    assert not preview.trusted_mapping_verified and not preview.execution_performed


@pytest.mark.parametrize("change", [{"service_id": "other-service"}, {"project_name": "other-project"},
                                   {"provider_scope": "other-scope"}, {"is_mock": False}])
def test_retained_reference_rejects_wrong_expected_binding(change):
    retained = build_mock_context()
    with pytest.raises(CollectionContextError):
        retained.verify_request(retained.to_request(), expected_binding=replace(mock_context_binding(), **change))


def test_identical_snapshot_does_not_prove_collection_association():
    first, second = build_mock_context("withheld"), build_mock_context("unavailable")
    assert first.to_request()["snapshot"] == second.to_request()["snapshot"]
    with pytest.raises(CollectionContextError):
        first.verify_request(second.to_request(), expected_binding=mock_context_binding())
    claim = proposed(second.to_request())
    validate_contextual_request(claim)
    with pytest.raises(ContextCompatibilityError, match="untrusted_service_mapping"):
        diagnose_contextual_request(claim)


def test_different_snapshot_context_is_rejected():
    first, second = build_mock_context("exported").to_request(), build_mock_context("withheld").to_request()
    first["collection_context"] = second["collection_context"]
    with pytest.raises(ContextCompatibilityError):
        validate_provider_context(first)


@pytest.mark.parametrize("name", MOCK_CONTEXT_SCENARIOS)
def test_actual_setup_companion_preserves_context_and_report(name):
    retained = build_mock_context(name)
    envelope = retained.to_request()
    request = problem(service_target="MOCK-service")
    evidence = service_evidence(request, **envelope["snapshot"])
    outcome = preserve_collection_context(request, evidence, prepared=retained, expected_binding=mock_context_binding())
    assert outcome.state == "context_preserved"
    with TestClient(create_app()) as client:
        response = client.post("/internal/triage/diagnose", json=envelope["snapshot"])
    attached = consume_collection_diagnosis_response(request, outcome.companion,
                                                      status_code=response.status_code, payload=response.json())
    assert attached.state == "diagnosis_associated"
    output = attached.to_dict()["companion"]
    assert output["collection_context"] == envelope["collection_context"]
    assert output["display"]["collection_errors"] == [
        item for item in envelope["collection_context"]["capabilities"] if item["error_code"] is not None
    ]
    assert output["diagnosis"]["report"] == response.json()
    assert output["production_readiness"] == "unresolved"
    assert not output["execution_performed"] and not output["execution_authorized"]


def test_actual_setup_rejects_json_as_backend_reference():
    envelope = build_mock_context().to_request()
    request = problem(service_target="MOCK-service")
    evidence = service_evidence(request, **envelope["snapshot"])
    rejected = preserve_collection_context(request, evidence, prepared=envelope, expected_binding=mock_context_binding())
    assert rejected.state == "unresolved" and rejected.companion is None
    assert rejected.errors[0].code == "producer_reference_required"
