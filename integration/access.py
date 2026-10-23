"""Authorization-enforcing facade for the existing finite Mock lifecycle.

Trusted Python composition owns dependencies. This is not isolation from code
that can directly access lower-level stores/workflows or rewrite local files.
"""

from .access_identity import RequestPermission, binding_reference, validate_resolution
from .access_store import SQLiteOwnershipStore
from .request_errors import RequestError
from .request_policy import digest, identifier
from .request_store import SQLiteRequestStore
from .requests import PersistentMockRequests
from provider.examples.context_fixtures import mock_context_binding


class ProtectedMockRequests:
    def __init__(self, request_store, owners, *, identity=None, expected_binding=None, mock=False):
        if mock is not True:
            raise RequestError("MOCK_OPT_IN_REQUIRED")
        if (type(request_store) is not SQLiteRequestStore or type(owners) is not SQLiteOwnershipStore
                or owners.request_storage != request_store.storage_reference()):
            raise RequestError("INVALID_DATABASE")
        self._owners = owners
        self._identity = identity  # None remains denied. No default identity issuer.
        self._expected = mock_context_binding() if expected_binding is None else expected_binding
        self._active_check = None
        self._evidence_access = {}
        self._workflow = PersistentMockRequests(request_store, mock=True, checkpoint=self._checkpoint)

    def __repr__(self):
        return "ProtectedMockRequests(mode='mock', execution='disabled')"

    def _checkpoint(self):
        if self._active_check is None:
            raise RequestError("ACCESS_DENIED")
        self._active_check()

    def _authorize(self, context, permission, request_id=None):
        try:
            if self._identity is None or context is None or self._expected != mock_context_binding():
                raise ValueError()
            access = validate_resolution(self._identity.resolve(context))
            binding = binding_reference(self._expected)
            if permission not in access.permissions or binding not in {binding_reference(b) for b in access.bindings}:
                raise ValueError()
            owner = None
            if request_id is not None:
                identifier(request_id)
                owner = self._owners.get(request_id)
                if owner is None or owner.owner_ref != access.actor.subject or owner.binding_ref != binding:
                    raise ValueError()
            signature = (access.actor.subject, access.generation, binding,
                         tuple(sorted(p.value for p in access.permissions)),
                         tuple(sorted(binding_reference(b) for b in access.bindings)),
                         owner.revision if owner is not None else None)
            return signature
        except RequestError as error:
            if error.code in ("STORAGE_BUSY", "STORAGE_FAILED", "STORE_CLOSED"):
                raise
            raise RequestError("ACCESS_DENIED") from None
        except Exception:
            raise RequestError("ACCESS_DENIED") from None

    def _drop_evidence(self, request_id):
        self._workflow._retained = {key: value for key, value in self._workflow._retained.items() if key[0] != request_id}
        self._evidence_access.pop(request_id, None)

    def _perform(self, context, permission, request_id, action):
        if self._active_check is not None or (permission is not RequestPermission.CREATE and request_id is None):
            raise RequestError("ACCESS_DENIED")  # One instance/thread; no reentrant operation.
        original = None
        try:
            original = self._authorize(context, permission, request_id)
            if request_id is not None and self._evidence_access.get(request_id) != original:
                self._drop_evidence(request_id)

            def check():
                if self._authorize(context, permission, request_id) != original:
                    raise RequestError("ACCESS_DENIED")

            self._active_check = check
            check()
            result = action(original)
            check()
            return result
        except RequestError as error:
            if error.code == "ACCESS_DENIED" and original is not None and type(request_id) is str:
                self._drop_evidence(request_id)
            raise
        finally:
            self._active_check = None

    @staticmethod
    def _key(public_key, signature):
        identifier(public_key)
        # Principal + complete target scope, not session lifetime or volatile grant generation.
        # The lower-level request command still rejects key/content/operation conflicts.
        return digest(["protected-mutation-v1", signature[0], signature[2], public_key])[7:39]

    def create(self, context, brief, *, idempotency_key):
        def action(signature):
            result = self._workflow.create(brief, idempotency_key=self._key(idempotency_key, signature))
            self._checkpoint()
            request_id = result["request"]["request_id"]
            self._owners.register(request_id, owner_ref=signature[0], binding_ref=signature[2], checkpoint=self._checkpoint)
            # A failed registration never returns the unowned request or its ID.
            self._authorize(context, RequestPermission.CREATE, request_id)
            return result
        return self._perform(context, RequestPermission.CREATE, None, action)

    def get(self, context, request_id):
        return self._perform(context, RequestPermission.READ, request_id, lambda _: self._workflow.get(request_id))

    def events(self, context, request_id, *, limit=20, before_revision=None):
        return self._perform(context, RequestPermission.READ, request_id,
                             lambda _: self._workflow.events(request_id, limit=limit, before_revision=before_revision))

    def supply_information(self, context, request_id, brief, *, expected_revision, idempotency_key):
        return self._perform(context, RequestPermission.COMPLETE, request_id, lambda signature:
            self._workflow.supply_information(request_id, brief, expected_revision=expected_revision,
                                             idempotency_key=self._key(idempotency_key, signature)))

    def recover(self, context, request_id, *, expected_revision, idempotency_key):
        return self._perform(context, RequestPermission.RECOVER, request_id, lambda signature:
            self._workflow.recover(request_id, expected_revision=expected_revision,
                                   idempotency_key=self._key(idempotency_key, signature)))

    def inspect(self, context, request_id, *, expected_revision, idempotency_key, history, scenario="partial_failure"):
        def action(signature):
            # The existing inspection response includes a linked historical summary.
            self._authorize(context, RequestPermission.HISTORY, request_id)
            self._evidence_access[request_id] = signature
            return self._workflow.inspect(request_id, expected_revision=expected_revision,
                idempotency_key=self._key(idempotency_key, signature), history=history, scenario=scenario)
        return self._perform(context, RequestPermission.INSPECT, request_id, action)

    def current_inspection(self, context, request_id, *, expected_revision):
        return self._perform(context, RequestPermission.INSPECT, request_id,
                             lambda _: self._workflow.current_inspection(request_id, expected_revision=expected_revision))

    def historical_summary(self, context, request_id, *, history, revision=None):
        return self._perform(context, RequestPermission.HISTORY, request_id,
                             lambda _: self._workflow.historical_summary(request_id, history=history, revision=revision))
