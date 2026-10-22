"""Rehearse the actual isolated demo, with no mocked diagnosis or authorization."""

import json
import socket
import subprocess
import sys

import pytest

from infrapilot_triage.api import app
from infrapilot_triage.demo import main, run_mock_demo
from infrapilot_triage.schemas import DiagnosisReport


@pytest.mark.parametrize("mock", [False, None, 1, "true"])
def test_demo_requires_explicit_mock_mode(mock) -> None:
    with pytest.raises(ValueError, match="MOCK"):
        run_mock_demo(mock=mock)


def test_complete_demo_never_connects_to_provider_or_executes(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args, **_kwargs):
        pytest.fail("Offline demo attempted a network connection or process execution")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    result = run_mock_demo(mock=True)
    assert result["mode"] == "MOCK_OFFLINE_IN_PROCESS"
    assert result["real_liara_connectivity_verified"] is False
    assert result["infrastructure_execution_performed"] is False
    for label, top in (("database_http500", "database_connection_failure"), ("cpu_latency", "cpu_saturation")):
        report = DiagnosisReport.model_validate(result[label]["response"]["body"])
        assert report.hypotheses[0].hypothesis_id == top
        assert report.data_source.value == "mock"
        assert all(action.status == "not_executed" for action in report.actions)
        assert any(action.requires_approval for action in report.actions)
    assert result["default_sensitive_route"]["http_status"] == 503
    assert result["policy"]["body"]["policy"]["requires_approval"] is True
    assert result["unapproved_denial"]["body"]["reason"] == "approval_required"
    assert result["pending_denial"]["body"]["reason"] == "approval_required"
    assert not result["mock_pending_python_only"]["allowed"]
    assert not result["mock_approved_python_only"]["allowed"]
    assert result["mock_authorization_not_execution"]["body"]["reason"] == "authorized_not_executed"
    assert result["replay_denial"]["body"]["reason"] == "approval_consumed"
    assert result["final_mock_approval_state"] == "consumed"
    assert result["audit_kinds"].count("authorization_consumed") == 1
    assert app.state.approval_integration is None and app.state.authentication_resolver is None


def test_cli_without_mock_opt_in_exits(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["demo"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "--mock" in capsys.readouterr().err


def test_cli_prints_structured_mock_output(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setattr(sys, "argv", ["demo", "--mock"])
    main()
    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "MOCK_OFFLINE_IN_PROCESS"
    assert result["infrastructure_execution_performed"] is False
