"""Existing workflow backed by real SQLite; no infrastructure authorization."""

from contextlib import ExitStack, redirect_stdout, redirect_stderr
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from infrapilot_triage import ApprovalGate, AuthenticatedActor
from infrapilot_triage.approval_store import StoreUnavailable
from infrapilot_triage.approvals import ApprovalState, DecisionReason
from provider import MockLiaraClient
from provider.models import ServiceLog
from infrapilot_triage import collection_context as context_module
from integration import workflow_demo
from integration.approval_store import SQLiteApprovalStore
from integration.mock_approval import approval_references
from integration.request_policy import digest
from integration.workflow import MOCK_GOAL, MockWorkflow, run_mock_workflow

CANARY = "PRIVATE-DURABLE-WORKFLOW-CANARY-662"
ROOT = Path(__file__).resolve().parents[2]


class DurableWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for target in ("socket.socket", "socket.create_connection", "urllib.request.build_opener", "subprocess.Popen"):
            self.stack.enter_context(patch(target, side_effect=AssertionError("External I/O forbidden")))
        self.stack.enter_context(patch.object(ApprovalGate, "authorize", side_effect=AssertionError("Consumption forbidden in workflow")))
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "approvals.sqlite"
        self.references = []

    def factory(self, **references):
        self.references.append(references)
        return SQLiteApprovalStore(self.path, **references)

    def ready(self, **options):
        workflow = MockWorkflow(mock=True, approval_store_factory=self.factory, **options)
        self.addCleanup(workflow.close)
        workflow.submit({"request_id": "MOCK-workflow-request", "operation": "inspect_service",
                         "details": {"service_target": "MOCK-service", "goal": MOCK_GOAL}})
        workflow.inspect()
        workflow.review_action()
        return workflow

    def test_actual_collector_diagnosis_gate_and_audits_connected_once(self):
        with patch.object(MockLiaraClient, "collect_service_observations", autospec=True,
                          side_effect=MockLiaraClient.collect_service_observations) as collect, patch.object(
                context_module, "diagnose", wraps=context_module.diagnose) as diagnose, patch.object(
                ApprovalGate, "request_approval", autospec=True, side_effect=ApprovalGate.request_approval) as request:
            result = run_mock_workflow(mock=True, scenario="approved_not_executed", approval_store_factory=self.factory)
        self.assertEqual(result.exit_code, 4)
        collect.assert_called_once()
        diagnose.assert_called_once()
        request.assert_called_once()
        view = result.to_dict()["stages"]["operator_example"]
        self.assertEqual(view["storage"], "local_sqlite")
        with SQLiteApprovalStore(self.path, **self.references[0], create=False) as reopened:
            self.assertEqual(reopened.get(view["current_approval"]["request_id"]).state, ApprovalState.APPROVED)
            self.assertEqual(len(reopened.events), 2)
        for flag in ("authorization_consumed", "execution_authorized", "execution_performed"):
            self.assertIs(view[flag], False)

    def test_existing_lifecycle_scenarios_use_persistent_gate(self):
        for scenario, state, count in (("approval_pending", ApprovalState.PENDING, 1),
                ("approved_not_executed", ApprovalState.APPROVED, 2), ("approval_rejected", ApprovalState.REJECTED, 2),
                ("approval_expired", ApprovalState.EXPIRED, 3)):
            result = run_mock_workflow(mock=True, scenario=scenario, approval_store_factory=self.factory)
            example = result.to_dict()["stages"]["operator_example"]
            with SQLiteApprovalStore(self.path, **self.references[-1], create=False) as store:
                self.assertEqual(store.get(example["current_approval"]["request_id"]).state, state)
                self.assertEqual(len(store.events), count)

    def test_restart_does_not_reconstruct_a_workflow_or_trust_from_stored_decision(self):
        first = self.ready()
        result = first.operator_example("approved_not_executed")
        old_session = first._operator.identity.requester_session
        record = result.to_dict()["stages"]["operator_example"]["current_approval"]
        first.close()
        with SQLiteApprovalStore(self.path, **self.references[-1], create=False) as store:
            gate = ApprovalGate(store=store, policy=first._operator.policy, clock=first._clock)
            self.assertEqual(gate.approve(record["request_id"], authentication=old_session).reason, DecisionReason.IDENTITY_UNAVAILABLE)
        second = self.ready()
        second.operator_example("approved_not_executed")
        self.assertNotEqual(self.references[0]["association_ref"], self.references[-1]["association_ref"])
        with self.assertRaises(StoreUnavailable):
            second._operator.store.get(record["request_id"])

    def test_changed_brief_closes_previous_store_and_drops_current_approval(self):
        workflow = self.ready()
        workflow.operator_example("approved_not_executed")
        old = workflow._operator
        workflow.supply_information({"goal": "Review this synthetic service again"})
        self.assertIsNone(workflow._operator)
        with self.assertRaises(StoreUnavailable):
            old.store.get(old._identifier)

    def test_persisted_fields_exclude_full_inspection_and_credentials(self):
        original = MockLiaraClient.get_logs
        def logs(client, *args, **kwargs):
            result = original(client, *args, **kwargs)
            return replace(result, data=[ServiceLog(CANARY, "stdout", "unverified")])
        with patch.object(MockLiaraClient, "get_logs", autospec=True, side_effect=logs) as collected:
            workflow = self.ready(collection_scenario="withheld")
            workflow.operator_example("approved_not_executed")
        collected.assert_called_once()
        text = self.path.read_bytes().decode("latin1")
        for forbidden in (CANARY, MOCK_GOAL, "collection_context", "diagnosis_binding", "companion_binding",
                          "Authorization", "Bearer", "MOCK log", "parameters_secret"):
            self.assertNotIn(forbidden, text)
        for value in (workflow._inspection.presentation.binding, workflow._inspection.companion.binding):
            self.assertNotIn(value, text)  # Only the combined association digest persists.

    def test_only_original_mock_inspection_can_select_workflow_association(self):
        workflow = self.ready()
        for submitted in (workflow._inspection.result.to_dict(), None,
                          replace(workflow._inspection, source_binding=replace(workflow._inspection.source_binding, is_mock=False))):
            with self.assertRaises(Exception):
                approval_references(submitted, retention_nonce=str(uuid4()))

    def test_factory_cannot_substitute_a_different_association(self):
        def foreign(**references):
            return SQLiteApprovalStore(self.path, **{**references, "association_ref": digest({"other": "review"})})
        result = run_mock_workflow(mock=True, scenario="approved_not_executed", approval_store_factory=foreign)
        self.assertEqual(result.exit_code, 2)
        self.assertFalse(result.to_dict()["execution_performed"])

    def invoke(self, args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = workflow_demo.main(args)
        self.assertEqual(stderr.getvalue(), "")
        self.assertNotIn(CANARY, stdout.getvalue())
        return code, json.loads(stdout.getvalue())

    def test_cli_persistent_mode_is_summary_only_and_closes_database(self):
        code, report = self.invoke(["--mock", "--scenario", "approved_not_executed", "--approval-database", str(self.path)])
        self.assertEqual(code, 4)
        self.assertEqual(report["approval_state"], "approved")
        self.assertEqual(report["audit_count"], 2)
        self.assertIs(report["storage_recorded"], True)
        for forbidden in ("stages", "current_approval", "actor_id", "request_id", "parameters", "approval_database"):
            self.assertNotIn(forbidden, report)
        self.assertFalse(report["execution_performed"])
        moved = self.path.with_suffix(".closed")
        self.path.rename(moved)  # Windows refuses this if a connection was leaked.

    def test_cli_no_opt_in_or_invalid_scenario_creates_no_database(self):
        for args in (["--approval-database", str(self.path)], ["--mock", "--scenario", CANARY, "--approval-database", str(self.path)]):
            self.assertEqual(self.invoke(args)[0], 3)
        self.assertFalse(self.path.exists())

    def test_cli_missing_parent_fails_closed_without_path_disclosure(self):
        path = Path(self.directory.name) / CANARY / "db"
        code, report = self.invoke(["--mock", "--scenario", "approved_not_executed", "--approval-database", str(path)])
        self.assertEqual(code, 2)
        self.assertFalse(report["execution_performed"])
        self.assertIs(report["storage_recorded"], False)
        self.assertFalse(path.exists())

    def test_no_approval_scenario_does_not_claim_a_record_was_stored(self):
        code, report = self.invoke(["--mock", "--approval-database", str(self.path)])
        self.assertEqual(code, 0)
        self.assertIs(report["storage_recorded"], False)
        self.assertFalse(self.path.exists())


class DurableWorkflowProcessTests(unittest.TestCase):
    def test_two_processes_use_existing_entry_point_without_restoring_contexts(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "approval.sqlite"
            args = [sys.executable, "-B", "-m", "integration.workflow_demo", "--mock", "--scenario", "approved_not_executed",
                    "--approval-database", str(path)]
            for _ in range(2):
                run = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=15)
                self.assertEqual(run.returncode, 4)
                self.assertEqual(run.stderr, "")
                report = json.loads(run.stdout)
                self.assertEqual(report["audit_count"], 2)
                self.assertFalse(report["execution_performed"])
            # Each run collected fresh synthetic evidence and requested approval
            # anew. This is persistence, not replay of an old trusted workflow.
            import sqlite3
            from contextlib import closing
            with closing(sqlite3.connect(path)) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM approvals").fetchone()[0], 2)
                self.assertEqual(db.execute("SELECT count(*) FROM audits").fetchone()[0], 4)

    def test_missing_dependencies_fail_before_creating_database(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / CANARY
            run = subprocess.run([sys.executable, "-B", "-S", "-m", "integration.workflow_demo", "--mock",
                                  "--approval-database", str(path)], cwd=ROOT, capture_output=True, text=True, timeout=10)
            self.assertEqual(run.returncode, 2)
            self.assertEqual(run.stderr, "")
            self.assertNotIn(CANARY, run.stdout)
            self.assertEqual(json.loads(run.stdout)["error_code"], "DEPENDENCIES_UNAVAILABLE")
            self.assertFalse(path.exists())
