"""Pure retained-association check shared by explicit Mock and read-only paths.

No client construction, diagnosis, identity, approval or execution occurs here.
"""

from provider import PreparedCollection, ServiceBinding
from setup.collection_context import CollectionCompanion
from setup.integration import request_fingerprint
from setup.triage import validate_presentation


def validate_retained_inspection(request, prepared, expected_binding, companion, presentation=None):
    """Return the current Setup view only after exact producer/brief checks."""
    if (type(prepared) is not PreparedCollection or type(expected_binding) is not ServiceBinding
            or type(companion) is not CollectionCompanion):
        raise ValueError("Retained producer and configured binding required.") from None
    envelope = prepared.verify_request(prepared.to_request(), expected_binding=expected_binding)
    view = companion.to_dict()
    if (envelope != {"snapshot": view["snapshot"], "collection_context": view["collection_context"]}
            or view["request_fingerprint"] != request_fingerprint(request)):
        raise ValueError("Inspection association changed.") from None
    if presentation is not None:
        validate_presentation(request, presentation)
        if (presentation.evidence.snapshot.model_dump(mode="json") != envelope["snapshot"]
                or presentation.evidence.association != companion.evidence.association
                or (view["diagnosis"] is not None and view["diagnosis"] != presentation.to_dict())):
            raise ValueError("Inspection diagnosis changed.") from None
    return view
