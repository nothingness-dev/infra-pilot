"""Explicit local mapping, validated before transport construction (no I/O)."""

from dataclasses import dataclass

from provider import ServiceBinding
from provider.environment import LiveSettings, read_live_settings

from .readonly_report import ReadOnlyError


@dataclass(frozen=True, repr=False)
class InspectionSettings:
    live: LiveSettings
    binding: ServiceBinding

    def __repr__(self):
        return "InspectionSettings(source='real', mapping='operator_configured')"


def read_inspection_settings(environment) -> InspectionSettings:
    try:
        live = read_live_settings(environment)
        binding = ServiceBinding(environment.get("LIARA_SERVICE_ID"), live.project,
                                 environment.get("LIARA_PROVIDER_SCOPE"), False)
        # Same no-secret-in-binding rule as the adapter, before client creation.
        token = live.config.api_key.get_secret_value()
        if any(token in value for value in (binding.service_id, binding.project_name, binding.provider_scope)):
            raise ValueError()
        return InspectionSettings(live, binding)
    except Exception:
        raise ReadOnlyError("INVALID_CONFIGURATION") from None
