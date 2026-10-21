"""Trusted local action classification; no provider capability assertions."""

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Annotated, Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, StringConstraints, ValidationError, model_validator

from .schemas import ActionProposal


ServiceIdentifier = Annotated[
    str, StringConstraints(strict=True, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$"),
]


class ActionType(str, Enum):
    INSPECT_SERVICE = "inspect_service"
    INSPECT_LOGS = "inspect_logs"
    INSPECT_METRICS = "inspect_metrics"
    REFRESH_OBSERVATIONS = "refresh_observations"
    RESTART_SERVICE = "restart_service"
    REDEPLOY_SERVICE = "redeploy_service"
    CHANGE_RESOURCES = "change_resources"
    MODIFY_PRODUCTION_CONFIG = "modify_production_config"
    DELETE_SERVICE = "delete_service"
    EXECUTE_COMMAND = "execute_command"


class ActionCategory(str, Enum):
    READ_ONLY = "read_only_inspection"
    LOW_RISK = "low_risk_operation"
    SENSITIVE = "sensitive_service_operation"
    DENIED = "destructive_or_unsupported"


class ActionIntent(BaseModel):
    """DRAFT local gate input; proposal text and safety labels are untrusted."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    service_id: ServiceIdentifier
    action_type: StrictStr
    parameters: dict[StrictStr, Any] = Field(default_factory=dict)
    proposal: ActionProposal | None = None


class _Parameters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class _LogParameters(_Parameters):
    limit: Annotated[StrictInt, Field(ge=1, le=1000)] = 100


class _RestartParameters(_Parameters):
    grace_period_seconds: Annotated[StrictInt, Field(ge=0, le=300)] = 30


class _RedeployParameters(_Parameters):
    artifact_digest: Annotated[StrictStr, Field(pattern=r"^sha256:[a-f0-9]{64}$")]


class _ResourceParameters(_Parameters):
    cpu_millicores: Annotated[StrictInt, Field(ge=1, le=1_000_000)] | None = None
    ram_mib: Annotated[StrictInt, Field(ge=1, le=1_000_000)] | None = None

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if self.cpu_millicores is None and self.ram_mib is None:
            raise ValueError("At least one resource parameter is required")
        return self


class _ProductionParameters(_Parameters):
    log_level: Literal["info", "warning", "error"] | None = None
    request_timeout_seconds: Annotated[StrictInt, Field(ge=1, le=300)] | None = None

    @model_validator(mode="after")
    def require_change(self) -> Self:
        if self.log_level is None and self.request_timeout_seconds is None:
            raise ValueError("At least one configuration parameter is required")
        return self


@dataclass(frozen=True)
class CanonicalAction:
    """Immutable decision payload; parameters returns a fresh decoded object."""

    service_id: str
    action_type: ActionType
    parameters_json: str
    policy_version: str
    fingerprint: str

    @property
    def parameters(self) -> dict[str, Any]:
        return json.loads(self.parameters_json)


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    category: ActionCategory
    requires_approval: bool
    reason: str
    action: CanonicalAction | None = None


_RULES: dict[ActionType, tuple[ActionCategory, type[_Parameters]]] = {
    ActionType.INSPECT_SERVICE: (ActionCategory.READ_ONLY, _Parameters),
    ActionType.INSPECT_LOGS: (ActionCategory.READ_ONLY, _LogParameters),
    ActionType.INSPECT_METRICS: (ActionCategory.READ_ONLY, _Parameters),
    ActionType.REFRESH_OBSERVATIONS: (ActionCategory.LOW_RISK, _Parameters),
    ActionType.RESTART_SERVICE: (ActionCategory.SENSITIVE, _RestartParameters),
    ActionType.REDEPLOY_SERVICE: (ActionCategory.SENSITIVE, _RedeployParameters),
    ActionType.CHANGE_RESOURCES: (ActionCategory.SENSITIVE, _ResourceParameters),
    ActionType.MODIFY_PRODUCTION_CONFIG: (ActionCategory.SENSITIVE, _ProductionParameters),
}


class ActionPolicy:
    """A server-installed allowlist, independent of Agent risk/approval labels."""

    VERSION = "triage-approval-v1"

    def classify(self, intent: ActionIntent) -> PolicyDecision:
        if not isinstance(self.VERSION, str) or not self.VERSION or self.VERSION.strip() != self.VERSION:
            return PolicyDecision(False, ActionCategory.DENIED, True, "policy_unavailable")
        try:
            if not isinstance(intent, ActionIntent):
                raise ValueError("ActionIntent required")
            # Revalidate mutated Pydantic/nested data; never trust a supplied hash.
            intent = ActionIntent.model_validate(intent.model_dump(warnings=False))
            action_type = ActionType(intent.action_type)
            rule = _RULES.get(action_type)
            if rule is None:
                return PolicyDecision(False, ActionCategory.DENIED, True, "unsupported_action")
            category, schema = rule
            parameters = schema.model_validate(intent.parameters).model_dump(exclude_none=True)
            parameters_json = json.dumps(parameters, sort_keys=True, separators=(",", ":"), allow_nan=False)
            payload = json.dumps({
                "policy_version": self.VERSION, "service_id": intent.service_id,
                "action_type": action_type.value, "parameters": parameters,
            }, sort_keys=True, separators=(",", ":"), allow_nan=False)
            action = CanonicalAction(
                service_id=intent.service_id, action_type=action_type,
                parameters_json=parameters_json, policy_version=self.VERSION,
                fingerprint=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            )
            return PolicyDecision(True, category, category == ActionCategory.SENSITIVE, "classified", action)
        except (ValueError, TypeError, ValidationError):
            # Never return validation text: it can contain user-supplied secrets.
            return PolicyDecision(False, ActionCategory.DENIED, True, "invalid_or_unknown_action")
