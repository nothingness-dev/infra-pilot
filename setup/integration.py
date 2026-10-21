"""Data-only references to teammate outputs; no adapters or policies."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DependencyInput:
    """A caller-supplied output reference or an explicit unavailability reason.

    Availability describes a preparation input, never permission to execute.
    The producer retains ownership of the referenced payload and its schema.
    """

    available: bool
    output_reference: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if type(self.available) is not bool:
            raise ValueError("available must be a boolean")
        if self.available:
            if not isinstance(self.output_reference, str) or not self.output_reference.strip():
                raise ValueError("an available input requires a nonblank output reference")
            if self.reason is not None:
                raise ValueError("an available input cannot have an unavailability reason")
        else:
            if not isinstance(self.reason, str) or not self.reason.strip():
                raise ValueError("an unavailable input requires a nonblank reason")
            if self.output_reference is not None:
                raise ValueError("an unavailable input cannot carry an output reference")


@dataclass(frozen=True)
class PreparationInputs:
    """Optional external results; absent inputs are unavailable, never fabricated."""

    provider: DependencyInput | None = None
    triage: DependencyInput | None = None

    def __post_init__(self) -> None:
        for value in (self.provider, self.triage):
            if value is not None and not isinstance(value, DependencyInput):
                raise ValueError("preparation inputs must be DependencyInput objects or None")
