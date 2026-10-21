"""Canonical classification tests without trusting diagnostic safety labels."""

from dataclasses import FrozenInstanceError
from typing import Any

import pytest
from pydantic import ValidationError

from infrapilot_triage import ActionProposal
from infrapilot_triage.policy import ActionCategory, ActionIntent, ActionPolicy, PolicyDecision


def classify(operation: str, parameters: dict[str, Any] | None = None) -> PolicyDecision:
    return ActionPolicy().classify(ActionIntent(
        service_id="service-A", action_type=operation, parameters=parameters or {},
    ))


@pytest.mark.parametrize("operation", ["inspect_service", "inspect_logs", "inspect_metrics"])
def test_read_only_action_policy(operation: str) -> None:
    result = classify(operation)
    assert result.allowed and not result.requires_approval
    assert result.category == ActionCategory.READ_ONLY


def test_low_risk_refresh_is_still_a_classified_operation() -> None:
    result = classify("refresh_observations")
    assert result.allowed and not result.requires_approval
    assert result.category == ActionCategory.LOW_RISK


@pytest.mark.parametrize("operation,parameters", [
    ("restart_service", {}),
    ("redeploy_service", {"artifact_digest": "sha256:" + "a" * 64}),
    ("change_resources", {"cpu_millicores": 500, "ram_mib": 512}),
    ("modify_production_config", {"log_level": "warning"}),
])
def test_sensitive_operations_always_require_approval(operation: str, parameters: dict[str, Any]) -> None:
    result = classify(operation, parameters)
    assert result.allowed and result.requires_approval
    assert result.category == ActionCategory.SENSITIVE


@pytest.mark.parametrize("operation", ["delete_service", "execute_command", "restart", "unknown", "RESTART_SERVICE"])
def test_destructive_or_unknown_operations_are_denied(operation: str) -> None:
    result = classify(operation)
    assert not result.allowed
    assert result.category == ActionCategory.DENIED
    assert result.action is None


@pytest.mark.parametrize("operation,parameters", [
    ("inspect_service", {"restart": True}),
    ("inspect_logs", {"limit": "100"}),
    ("inspect_logs", {"limit": True}),
    ("inspect_logs", {"limit": 1001}),
    ("restart_service", {"grace_period_seconds": -1}),
    ("restart_service", {"grace_period_seconds": 301}),
    ("restart_service", {"command": "arbitrary-command"}),
    ("redeploy_service", {"artifact_digest": "latest"}),
    ("change_resources", {}),
    ("change_resources", {"cpu_millicores": 1.5}),
    ("change_resources", {"ram_mib": True}),
    ("change_resources", {"ram_mib": 0}),
    ("modify_production_config", {}),
    ("modify_production_config", {"request_timeout_seconds": "30"}),
    ("modify_production_config", {"log_level": "debug"}),
    ("modify_production_config", {"environment": {"arbitrary": "value"}}),
])
def test_parameters_are_strictly_allowlisted(operation: str, parameters: dict[str, Any]) -> None:
    assert not classify(operation, parameters).allowed


def test_agent_safe_labels_do_not_change_classification_or_fingerprint() -> None:
    proposal = ActionProposal(
        action_id="restart_service", title="Safe inspection", description="Untrusted Agent assertion.",
        risk_level="low", requires_approval=False,
    )
    intent = ActionIntent(service_id="service-A", action_type="restart_service", proposal=proposal)
    decision = ActionPolicy().classify(intent)
    assert decision.requires_approval
    assert decision.action == classify("restart_service").action


def test_default_parameters_and_order_are_canonicalized() -> None:
    assert classify("restart_service").action == classify("restart_service", {"grace_period_seconds": 30}).action
    left = classify("change_resources", {"ram_mib": 512, "cpu_millicores": 500}).action
    right = classify("change_resources", {"cpu_millicores": 500, "ram_mib": 512}).action
    assert left == right
    assert left is not None and left.parameters == {"cpu_millicores": 500, "ram_mib": 512}


def test_fingerprint_binds_service_operation_parameters_and_policy_version() -> None:
    policy = ActionPolicy()
    intent = ActionIntent(service_id="service-A", action_type="restart_service")
    original = policy.classify(intent).action
    assert original is not None
    variants = [
        intent.model_copy(update={"service_id": "service-B"}),
        intent.model_copy(update={"action_type": "inspect_service"}),
        intent.model_copy(update={"parameters": {"grace_period_seconds": 10}}),
    ]
    assert all(policy.classify(variant).action.fingerprint != original.fingerprint for variant in variants)
    policy.VERSION = "changed-policy"
    assert policy.classify(intent).action.fingerprint != original.fingerprint


def test_canonical_action_cannot_be_changed_through_returned_parameters() -> None:
    action = classify("restart_service").action
    assert action is not None
    action.parameters["grace_period_seconds"] = 0
    assert action.parameters["grace_period_seconds"] == 30
    with pytest.raises(FrozenInstanceError):
        action.service_id = "service-B"


@pytest.mark.parametrize("service", ["", " service-A", "service-A ", "service\nA", "service-A\n", "../service"])
def test_service_identifiers_are_exact_and_validated(service: str) -> None:
    with pytest.raises(ValidationError):
        ActionIntent(service_id=service, action_type="restart_service")


def test_mutated_intent_parameters_are_revalidated() -> None:
    intent = ActionIntent(service_id="service-A", action_type="restart_service")
    intent.parameters["unknown"] = True
    assert not ActionPolicy().classify(intent).allowed


@pytest.mark.parametrize("version", [None, "", " "])
def test_missing_policy_version_fails_closed(version: Any) -> None:
    policy = ActionPolicy()
    policy.VERSION = version
    assert not policy.classify(ActionIntent(service_id="service-A", action_type="restart_service")).allowed
