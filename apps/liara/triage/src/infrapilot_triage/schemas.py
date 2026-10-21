"""Proposed internal schemas; these are not official Liara API models."""

from enum import Enum
from typing import Annotated, Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    model_validator,
)

NonEmptyText = Annotated[
    str, StringConstraints(strict=True, strip_whitespace=True, min_length=1)
]
NonNegativeNumber = Annotated[
    float, Field(strict=True, ge=0, allow_inf_nan=False)
]
Percentage = Annotated[
    float, Field(strict=True, ge=0, le=100, allow_inf_nan=False)
]
Confidence = Annotated[
    float, Field(strict=True, ge=0, le=1, allow_inf_nan=False)
]
HttpStatus = Annotated[StrictInt, Field(ge=100, le=599)]


class DataSource(str, Enum):
    REAL = "real"
    MOCK = "mock"


class ServiceStatus(str, Enum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class LogLevel(str, Enum):
    UNKNOWN = "unknown"
    TRACE = "trace"
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class EvidenceKind(str, Enum):
    STATUS = "status"
    HTTP = "http"
    METRIC = "metric"
    LOG = "log"


class RiskLevel(str, Enum):
    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ContractModel(BaseModel):
    """Reject unexpected fields so integration mismatches surface early."""

    model_config = ConfigDict(extra="forbid", validate_default=True)


class LogEntry(ContractModel):
    # Preserve log text verbatim, including whitespace and empty messages.
    message: StrictStr
    level: LogLevel = LogLevel.UNKNOWN
    timestamp: AwareDatetime | None = None


class ServiceSnapshot(ContractModel):
    service_id: NonEmptyText
    status: ServiceStatus
    data_source: DataSource
    http_status: HttpStatus | None = None
    cpu_usage_percent: Percentage | None = None
    ram_usage_mib: NonNegativeNumber | None = None
    response_time_ms: NonNegativeNumber | None = None
    # None means unavailable; [] means collected with no entries returned.
    logs: list[LogEntry] | None = None
    timestamp: AwareDatetime | None = None


class Evidence(ContractModel):
    evidence_id: NonEmptyText
    kind: EvidenceKind
    description: NonEmptyText


class DiagnosticHypothesis(ContractModel):
    hypothesis_id: NonEmptyText
    explanation: NonEmptyText
    confidence: Confidence
    evidence_ids: list[NonEmptyText] = Field(default_factory=list)


class ActionProposal(ContractModel):
    action_id: NonEmptyText
    title: NonEmptyText
    description: NonEmptyText
    risk_level: RiskLevel
    # Explicit input only: this schema does not evaluate approval policy.
    requires_approval: StrictBool
    status: Literal["not_executed"] = "not_executed"


class DiagnosisReport(ContractModel):
    service_id: NonEmptyText
    summary: NonEmptyText
    data_source: DataSource
    evidence: list[Evidence] = Field(default_factory=list)
    # Producer supplies descending confidence order; validation never reorders.
    hypotheses: list[DiagnosticHypothesis] = Field(default_factory=list)
    actions: list[ActionProposal] = Field(default_factory=list)
    missing_information: list[NonEmptyText] = Field(default_factory=list)
    limitations: list[NonEmptyText] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_report_links_and_ranking(self) -> Self:
        identifiers = {
            "evidence": [item.evidence_id for item in self.evidence],
            "hypotheses": [item.hypothesis_id for item in self.hypotheses],
            "actions": [item.action_id for item in self.actions],
        }
        for collection, values in identifiers.items():
            if len(values) != len(set(values)):
                raise ValueError(f"Duplicate identifiers in {collection}")

        evidence_ids = set(identifiers["evidence"])
        for hypothesis in self.hypotheses:
            if not set(hypothesis.evidence_ids).issubset(evidence_ids):
                raise ValueError("Hypothesis references unknown evidence")

        scores = [hypothesis.confidence for hypothesis in self.hypotheses]
        if any(left < right for left, right in zip(scores, scores[1:])):
            raise ValueError("Hypotheses must be ranked by descending confidence")
        return self
