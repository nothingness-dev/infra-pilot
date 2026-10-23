"""Deliberately finite Mock brief vocabulary; no free-text persistence."""

import hashlib
import json
import re

from provider.examples.context_fixtures import MOCK_CONTEXT_SCENARIOS as SCENARIOS
from setup.application import submit_request, supply_information
from setup.integration import request_fingerprint
from setup.models import OperationRequest
from setup.validation import validate_request
from .request_errors import RequestError

GOALS = {"review": "Review this synthetic service collection", "review_again": "Review this synthetic service again"}
TARGET = "MOCK-service"


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def digest(value):
    return "sha256:" + hashlib.sha256(canonical(value).encode("ascii")).hexdigest()


def identifier(value):
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{32}", value) is None:
        raise RequestError("INVALID_LOOKUP") from None
    return value


def positive(value):
    if type(value) is not int or not 1 <= value <= 2**53 - 1:
        raise RequestError("INVALID_LOOKUP") from None
    return value


def hash_value(value):
    return type(value) is str and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


def details(value):
    if type(value) is not dict or len(value) > 2 or any(type(k) is not str for k in value):
        raise RequestError("INVALID_REQUEST") from None
    for key, item in value.items():
        allowed = (TARGET,) if key == "service_target" else tuple(GOALS.values()) if key == "goal" else ()
        if type(item) is not str or item not in allowed:
            raise RequestError("INVALID_REQUEST") from None
    return dict(value)


def operation(request_id, brief):
    return OperationRequest(identifier(request_id), "inspect_service", details(brief))


def fingerprint(request_id, brief):
    request = operation(request_id, brief)
    return request_fingerprint(request) if validate_request(request).is_complete else None


def accept(request_id, brief, *, previous=None):
    """Invoke real Setup intake/completion; persist only its accepted brief."""
    brief = details(brief)
    payload = {"request_id": identifier(request_id), "operation": "inspect_service", "details": previous or {}}
    result = (submit_request({**payload, "details": brief}) if previous is None
              else supply_information(payload, brief))
    accepted = result.get("request")
    if (type(accepted) is not dict or accepted.get("request_id") != request_id
            or accepted.get("operation") != "inspect_service"):
        raise RequestError("INVALID_REQUEST") from None
    return details(accepted["details"])
