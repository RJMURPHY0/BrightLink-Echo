"""Retry a BrightLink request once after an unauthorised response."""

from urllib.error import HTTPError

from auth import _is_definitive_auth_error


def _is_unauthorised(exc: Exception) -> bool:
    response = getattr(exc, "response", None)
    status = (getattr(exc, "status_code", None)
              or getattr(exc, "status", None)
              or getattr(response, "status_code", None)
              or getattr(exc, "code", None))
    try:
        return int(status) == 401
    except (TypeError, ValueError):
        return status == "PGRST303" or (isinstance(exc, HTTPError)
                                         and exc.code == 401)


def call_with_auth_retry(operation, auth, on_expired):
    """Run operation, refresh on 401, then retry that operation at most once.

    A failed refresh preserves the original 401. Only a definitive auth
    verdict ends the local session. Network failures never end it.
    """
    try:
        return operation()
    except Exception as original:
        if not _is_unauthorised(original) or auth is None:
            raise
        try:
            auth.refresh_session()
        except Exception as refresh_error:
            print(f"[Auth] Refresh after 401 failed: {type(refresh_error).__name__}: {refresh_error}")
            if _is_definitive_auth_error(str(refresh_error)) and on_expired:
                on_expired()
            raise original from refresh_error
        return operation()


class RetryingSupabaseClient:
    """Pass PostgREST and storage calls through the same 401 handler."""

    def __init__(self, client, auth, on_expired):
        self._client = client
        self._auth = auth
        self._on_expired = on_expired

    def __getattr__(self, name):
        return getattr(self._client, name)

    def table(self, name):
        return _RetryingQuery(self._client.table(name), self._auth,
                              self._on_expired)

    def rpc(self, name, params=None):
        return _RetryingQuery(self._client.rpc(name, params), self._auth,
                              self._on_expired)

    @property
    def storage(self):
        return _RetryingStorage(self._client.storage, self._auth,
                                self._on_expired)


class _RetryingQuery:
    def __init__(self, query, auth, on_expired):
        self._query = query
        self._auth = auth
        self._on_expired = on_expired

    def __getattr__(self, name):
        member = getattr(self._query, name)
        if name == "execute":
            return lambda *a, **kw: call_with_auth_retry(
                lambda: member(*a, **kw), self._auth, self._on_expired)
        if not callable(member):
            return member

        def chained(*a, **kw):
            result = member(*a, **kw)
            if hasattr(result, "execute"):
                return _RetryingQuery(result, self._auth, self._on_expired)
            return result
        return chained


class _RetryingStorage:
    def __init__(self, storage, auth, on_expired):
        self._storage = storage
        self._auth = auth
        self._on_expired = on_expired

    def __getattr__(self, name):
        return getattr(self._storage, name)

    def from_(self, bucket):
        return _RetryingBucket(self._storage.from_(bucket), self._auth,
                               self._on_expired)


class _RetryingBucket:
    def __init__(self, bucket, auth, on_expired):
        self._bucket = bucket
        self._auth = auth
        self._on_expired = on_expired

    def __getattr__(self, name):
        member = getattr(self._bucket, name)
        if name not in {"upload", "download", "list", "remove", "update", "move", "copy"}:
            return member
        return lambda *a, **kw: call_with_auth_retry(
            lambda: member(*a, **kw), self._auth, self._on_expired)
