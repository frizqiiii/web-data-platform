"""Credential resolution abstraction (Phase 3).

`Scraper.credential_reference` (Phase 2) is a plain string identifier
— "look up a credential named this, elsewhere" — not a secret store,
and nothing in this codebase resolves it to an actual credential
value yet (that is a future increment's job: a real secret-backend
`CredentialProvider` implementation). This module only defines the
*shape* of that resolution step and a safe default.

Fail-closed is the entire point of this abstraction: if a scraper
declares a `credential_reference` and the configured provider cannot
produce a value for it, the engine MUST NOT make the request anyway
(e.g. unauthenticated, or with the reference string itself sent as
if it were the secret). See `worker.engines.http.engine` for where
this is enforced — before any network call is made.
"""

from typing import Protocol


class CredentialProvider(Protocol):
    async def get_credential(self, reference: str) -> str | None: ...


class NullCredentialProvider:
    """The only provider that exists in Phase 3. Always returns
    None, which — combined with the fail-closed check at the engine
    level — means any scraper with a `credential_reference` set
    currently cannot execute at all (CREDENTIAL_UNAVAILABLE), rather
    than silently executing unauthenticated. That is intentional:
    there is no way, in Phase 3, to correctly resolve a credential,
    so refusing to run is the only safe behavior.
    """

    async def get_credential(self, reference: str) -> str | None:
        return None
