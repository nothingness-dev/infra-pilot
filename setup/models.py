"""Local proposals only; these are not approved shared team contracts."""

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Literal, Mapping


class Operation(str, Enum):
    SETUP_SERVICE = "setup_service"
    INSPECT_SERVICE = "inspect_service"


class WorkflowState(str, Enum):
    RECEIVED = "received"
    NEEDS_INFORMATION = "needs_information"
    PLAN_PREPARED = "plan_prepared"
    BLOCKED = "blocked"


class DependencyPhase(str, Enum):
    PREPARATION = "preparation"
    EXECUTION = "execution"


@dataclass(frozen=True)
class OperationRequest:
    request_id: str
    operation: str
    details: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MissingInformation:
    field: str
    message: str


@dataclass(frozen=True)
class StructuredError:
    code: str
    message: str
    field: str | None = None


@dataclass(frozen=True)
class Dependency:
    key: str
    phase: DependencyPhase
    available: bool
    reason: str
    output_reference: str | None = None

    def to_dict(self) -> dict:
        return {**asdict(self), "phase": self.phase.value}


@dataclass(frozen=True)
class WorkflowStep:
    key: str
    description: str
    dependency_keys: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        return {**asdict(self), "dependency_keys": list(self.dependency_keys)}


@dataclass(frozen=True)
class OperationPlan:
    request_id: str
    operation: str
    collected_information: Mapping[str, str]
    missing_information: tuple[MissingInformation, ...]
    proposed_steps: tuple[WorkflowStep, ...]
    dependencies: tuple[Dependency, ...]
    execution_performed: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "operation": self.operation,
            "collected_information": dict(self.collected_information),
            "missing_information": [asdict(item) for item in self.missing_information],
            "proposed_steps": [step.to_dict() for step in self.proposed_steps],
            "dependencies": [item.to_dict() for item in self.dependencies],
            "execution_performed": self.execution_performed,
            "execution_authorized": self.execution_authorized,
        }


@dataclass(frozen=True)
class PreparationResult:
    request_id: str | None
    state: WorkflowState
    state_history: tuple[WorkflowState, ...]
    collected_information: Mapping[str, str]
    missing_information: tuple[MissingInformation, ...] = ()
    errors: tuple[StructuredError, ...] = ()
    plan: OperationPlan | None = None
    execution_performed: Literal[False] = field(default=False, init=False)
    execution_authorized: Literal[False] = field(default=False, init=False)

    def to_dict(self) -> dict:
        """Return a detached JSON-compatible representation for a future UI."""
        return {
            "request_id": self.request_id,
            "state": self.state.value,
            "state_history": [state.value for state in self.state_history],
            "collected_information": dict(self.collected_information),
            "missing_information": [asdict(item) for item in self.missing_information],
            "errors": [asdict(item) for item in self.errors],
            "plan": self.plan.to_dict() if self.plan else None,
            "execution_performed": self.execution_performed,
            "execution_authorized": self.execution_authorized,
        }
