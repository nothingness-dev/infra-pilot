"""Conservative observation comparison, separate from action/causality claims."""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
import json

from infrapilot_triage import ActionIntent, ActionPolicy
from infrapilot_triage.symptoms import DiagnosisThresholds, Symptom, extract_symptoms

from .mock_approval import MockClock
from .outcome_evidence import EvidenceLedger, EvidenceRef, OutcomeError, canonical
from .workflow import MockWorkflow


OUTCOME_VERSION = "infrapilot-evidence-outcome/1-mock"
POLICY_VERSION = "controlled-observation-comparison/1"
_HEALTH = {"healthy": 0, "degraded": 1, "unhealthy": 2}


@dataclass(frozen=True)
class OutcomeResult:
    _json: str = field(repr=False)
    exit_code: int

    def to_dict(self) -> dict:
        return json.loads(self._json)


class SimulatedActionRef:
    __slots__ = ()

    def __new__(cls):
        raise OutcomeError("INVALID_ACTION_REFERENCE") from None

    def __repr__(self):
        return "SimulatedActionRef(mode='mock', real_execution=False)"


class OutcomeEvaluator:
    """Trusted, process-local Mock comparison scope; no serialized resume API.

    Controlled canonical samples have explicit app-probe semantics, unlike
    Provider's unknown-unit/time fixtures. Simulation records are private
    synthetic events, not execution receipts or approvals.
    """

    def __init__(self, *, mock=False, clock=None, request=None, binding=None):
        self.evidence = EvidenceLedger(mock=mock, request=request, binding=binding)
        self.clock = clock if clock is not None else MockClock()
        self.thresholds = DiagnosisThresholds()
        self._actions = {}

    def __repr__(self):
        return "OutcomeEvaluator(mode='mock', execution='disabled')"

    def _now(self):
        try:
            now = self.clock()
            if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
                raise ValueError()
            return now.astimezone(timezone.utc)
        except Exception:
            raise OutcomeError("CLOCK_UNAVAILABLE") from None

    def _result(self, state, observation="not_performed", *, before=None, after=None, changes=None,
                limitations=(), error=None, action_status="unknown_unverified", action=None):
        data = {
            "contract_version": OUTCOME_VERSION, "policy_version": POLICY_VERSION, "mode": "mock",
            "evaluation_state": state, "observation_result": observation,
            "association_status": ("rejected" if state == "rejected" else "validated_mock_bindings" if before is not None else "not_established"),
            "comparison_scope": ["reported_health", "server_error_indicator", "slow_response_indicator"],
            "policy": {"slow_response_ms": self.thresholds.slow_response_ms,
                       "controlled_sample_max_age_seconds": 60, "resources_directional": False},
            "evidence": {"before": before, "after": after}, "changes": changes or [],
            "limitations": list(dict.fromkeys((
                "NO_EXECUTION_OR_CAUSALITY_PROOF", "COMPARISON_IS_NOT_SERVICE_RECOVERY",
                "LOG_ABSENCE_AND_DIAGNOSIS_CONFIDENCE_NOT_COMPARED", *limitations,
            ))), "error_code": OutcomeError(error).code if error is not None else None,
            "action": {"status": action_status, "simulation": action},
            "post_action_evaluation": "simulated_only" if action_status == "simulated" and state == "evaluated" else "not_performed",
            "causality_established": False, "remediation_verified": False,
            "authorization_consumed": False, "execution_authorized": False, "execution_performed": False,
            "production_readiness": "unresolved",
        }
        code = 2 if state == "failed" else 3 if state == "rejected" else 4 if state == "not_performed" else 1 if state == "insufficient_evidence" else 0
        return OutcomeResult(canonical(data), code)

    def rejection(self, error: OutcomeError, *, before=None) -> OutcomeResult:
        """Safe capture-failure boundary, retaining only independently valid before data."""
        try:
            summary = self.evidence.summary(before) if before is not None else None
        except Exception:
            summary = None
        code = error.code if type(error) is OutcomeError else "UNEXPECTED_ERROR"
        return self._result("rejected", "rejected_association", before=summary, error=code)

    def failed(self, *, before=None) -> OutcomeResult:
        """An unexpected later collection failure must not erase valid before data."""
        try:
            summary = self.evidence.summary(before) if before is not None else None
        except Exception:
            summary = None
        return self._result("failed", before=summary, error="UNEXPECTED_ERROR")

    def record_simulated_action(self, before: EvidenceRef, *, mock=False) -> SimulatedActionRef:
        if mock is not True:
            raise OutcomeError("MOCK_OPT_IN_REQUIRED") from None
        entry = self.evidence.check(before)
        if entry.kind != "controlled_canonical":
            raise OutcomeError("INVALID_ACTION_REFERENCE") from None
        action = ActionPolicy().classify(ActionIntent(service_id=self.evidence.binding.service_id,
                                                     action_type="restart_service", parameters={"grace_period_seconds": 30}))
        if not action.allowed or action.action is None:
            raise OutcomeError("ACTION_MISMATCH") from None
        reference = object.__new__(SimulatedActionRef)
        # Retain identity and canonical immutable fields, not caller JSON claims.
        self._actions[reference] = (before, self.evidence.fingerprint, action.action, self._now())
        return reference

    def _action(self, reference, before):
        if type(reference) is not SimulatedActionRef or reference not in self._actions:
            raise OutcomeError("INVALID_ACTION_REFERENCE") from None
        original_before, fingerprint, action, occurred_at = self._actions[reference]
        expected = ActionPolicy().classify(ActionIntent(service_id=self.evidence.binding.service_id,
                                                       action_type="restart_service", parameters={"grace_period_seconds": 30})).action
        if original_before is not before or fingerprint != self.evidence.fingerprint or action != expected:
            raise OutcomeError("ACTION_MISMATCH") from None
        return {"kind": "controlled_synthetic_event_not_execution_receipt", "occurred_at": occurred_at.isoformat(),
                "canonical_action": {**asdict(action), "action_type": action.action_type.value},
                "provider_support": "unverified", "real_execution": False}, occurred_at

    def compare(self, before: EvidenceRef, after: EvidenceRef, *, simulation=None) -> OutcomeResult:
        """Compare only retained evidence. Optional simulation never proves execution."""
        first_summary, second_summary = None, None
        try:
            first = self.evidence.check(before)
            first_summary = self.evidence.summary(before)
            second = self.evidence.check(after)
            second_summary = self.evidence.summary(after)
            if first.kind != second.kind:
                raise OutcomeError("SOURCE_MISMATCH")
            action, action_time = self._action(simulation, before) if simulation is not None else (None, None)
            action_status = "simulated" if action is not None else "unknown_unverified"
            common = {"before": first_summary, "after": second_summary, "action_status": action_status, "action": action}
            if first.sequence >= second.sequence:
                return self._result("insufficient_evidence", "insufficient_comparable_evidence", **common,
                                    limitations=("RETAINED_COLLECTION_ORDER_NOT_ESTABLISHED",))
            if first.kind == "provider_mock":
                # Existing producer fixture times can be identical. Invocation
                # order is not evidence that the samples form a before/after pair.
                return self._result("insufficient_evidence", "insufficient_comparable_evidence", **common,
                                    limitations=("PROVIDER_OBSERVATION_TIMES_AND_WINDOWS_UNVERIFIED",
                                                 "PROVIDER_FIXTURE_COLLECTION_ORDER_NOT_ESTABLISHED",
                                                 "PROVIDER_METRIC_UNITS_UNVERIFIED"))
            if first.semantics != second.semantics:
                return self._result("insufficient_evidence", "insufficient_comparable_evidence", **common,
                                    limitations=("MEASUREMENT_SEMANTICS_MISMATCH",))
            left, right = first.presentation.evidence.snapshot, second.presentation.evidence.snapshot
            now = self._now()
            reason = self._ordering(left.timestamp, right.timestamp, now, action_time)
            if reason is not None:
                return self._result("insufficient_evidence", "insufficient_comparable_evidence", **common, limitations=(reason,))
            changes, result, limits = self._compare_fields(left, right)
            return self._result("insufficient_evidence" if result == "insufficient_comparable_evidence" else "evaluated",
                                result, **common, changes=changes, limitations=limits)
        except OutcomeError as error:
            return self._result("rejected", "rejected_association", before=first_summary, after=None, error=error.code)
        except Exception:
            return self._result("failed", before=first_summary, after=second_summary, error="UNEXPECTED_ERROR")

    @staticmethod
    def _ordering(before, after, now, action_time):
        if before is None or after is None:
            return "OBSERVATION_TIME_UNVERIFIED"
        if before >= after:
            return "OBSERVATION_ORDER_AMBIGUOUS_OR_REVERSED"
        if after > now or before > now:
            return "OBSERVATION_TIME_IN_FUTURE"
        # Explicit policy only for controlled synthetic samples, never live TTL.
        if now - before > timedelta(seconds=60) or now - after > timedelta(seconds=60):
            return "CONTROLLED_SAMPLE_TOO_OLD"
        if action_time is not None and not before < action_time < after:
            return "SIMULATED_ACTION_NOT_BETWEEN_OBSERVATIONS"
        return None

    def _compare_fields(self, before, after):
        left_signals = extract_symptoms(before, thresholds=self.thresholds)
        right_signals = extract_symptoms(after, thresholds=self.thresholds)
        rows, directions, limits = [], set(), []
        comparable = 0
        coverage_changed = False
        for name, symptom in (("status", None), ("http_status", Symptom.HTTP_SERVER_ERROR),
                              ("response_time_ms", Symptom.SLOW_RESPONSE)):
            old, new = getattr(before, name), getattr(after, name)
            old = old.value if name == "status" else old
            new = new.value if name == "status" else new
            missing_old = old is None or old == "unknown"
            missing_new = new is None or new == "unknown"
            if missing_old or missing_new:
                coverage_changed |= missing_old != missing_new
                rows.append({"field": name, "before": old, "after": new, "change": "not_comparable"})
                continue
            comparable += 1
            a, b = ((_HEALTH[old], _HEALTH[new]) if name == "status" else
                    (int(left_signals.has(symptom)), int(right_signals.has(symptom))))
            direction = "improved" if b < a else "deteriorated" if b > a else "unchanged_indicator"
            rows.append({"field": name, "before": old, "after": new, "change": direction})
            if direction != "unchanged_indicator":
                directions.add(direction)
        for name, unit in (("cpu_usage_percent", "%"), ("ram_usage_mib", "MiB")):
            old, new = getattr(before, name), getattr(after, name)
            rows.append({"field": name, "unit": unit, "before": old, "after": new,
                         "change": "context_only" if old is not None and new is not None else "not_comparable",
                         "delta": new - old if old is not None and new is not None else None})
        limits.extend(("RESOURCE_DELTAS_NOT_SERVICE_RECOVERY", "ONLY_HEALTH_SERVER_ERROR_AND_LATENCY_INDICATORS_SUMMARIZED",
                       "HTTP_NON_SERVER_ERRORS_NOT_CLASSIFIED", "UNCHANGED_MEANS_SAME_POLICY_INDICATORS_NOT_IDENTICAL_DATA",
                       "FRESHNESS_CHECK_APPLIES_ONLY_TO_CONTROLLED_SYNTHETIC_SAMPLES"))
        if coverage_changed or not comparable:
            return rows, "insufficient_comparable_evidence", (*limits, "PRIMARY_EVIDENCE_COVERAGE_CHANGED" if coverage_changed else "NO_COMPARABLE_PRIMARY_INDICATORS")
        if comparable < 3:
            limits.append("SOME_PRIMARY_INDICATORS_UNAVAILABLE")
        result = ("mixed_changes" if len(directions) == 2 else "observed_improvement" if directions == {"improved"}
                  else "observed_deterioration" if directions == {"deteriorated"} else "no_material_observed_change")
        return rows, result, limits

    def evaluate_unexecuted_workflow(self, workflow: MockWorkflow) -> OutcomeResult:
        """The existing typed workflow has no executor, irrespective of approval."""
        reference = None
        try:
            if type(workflow) is not MockWorkflow:
                raise OutcomeError("INVALID_ACTION_REFERENCE")
            workflow._current()  # Reuse actual backend request/evidence validation.
            if workflow._operator is not None:
                workflow._operator.to_dict()  # Revalidate the original action binding.
            reference = self.evidence.retain_provider(workflow._inspection)
            return self._result("not_performed", before=self.evidence.summary(reference), action_status="not_performed",
                                limitations=("WORKFLOW_HAS_NO_EXECUTOR", "APPROVAL_DOES_NOT_ESTABLISH_EXECUTION"))
        except OutcomeError as error:
            return self.rejection(error, before=reference)
        except Exception:
            return self.rejection(OutcomeError("INVALID_ACTION_REFERENCE"), before=reference)
