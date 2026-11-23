"""Maps an `ExecutionContext.engine` string to the `EngineAdapter`
that handles it.

The three engine-name strings here ("HTTP", "BROWSER", "SCRAPY") are
a deliberate, intentional duplication of `app.models.scraper.
ScraperEngine`'s values, not a shared import of that enum — the
worker must not import from `app.*` (Section 5/11: no FastAPI, no
ORM, no database session reachable from the execution layer), the
same reasoning ADR-002 already applies to `WorkerSettings` duplicating
`redis_url` instead of importing the API's `Settings`. Whatever
assembles an `ExecutionContext` (Phase 4/5's dispatch code, which
*does* have access to `ScraperEngine`) is responsible for putting the
matching string value into `ExecutionContext.engine`.
"""

from worker.core.credentials import CredentialProvider, NullCredentialProvider
from worker.engines.base import EngineAdapter
from worker.engines.browser.engine import BrowserEngineAdapter
from worker.engines.http.engine import HttpEngineAdapter
from worker.engines.scrapy.engine import ScrapyEngineAdapter

HTTP = "HTTP"
BROWSER = "BROWSER"
SCRAPY = "SCRAPY"


class UnknownEngineError(ValueError):
    """Raised when `ExecutionContext.engine` is not one of the known
    engine names. This is a caller bug (an ExecutionContext should
    never be constructed with an engine value Phase 2's
    `ScraperEngine` doesn't recognize) — not a classified
    `ExecutionError`, since there is no engine to even attempt
    classifying the failure through."""


class EngineResolver:
    """Built once (e.g. at worker startup) with a `CredentialProvider`,
    then reused to resolve every execution's adapter — this is NOT a
    per-execution object, since the HTTP engine's own state (its
    injectable resolver, timeouts) is per-call, not per-resolver.
    """

    def __init__(self, credential_provider: CredentialProvider | None = None) -> None:
        provider = credential_provider or NullCredentialProvider()
        self._adapters: dict[str, EngineAdapter] = {
            HTTP: HttpEngineAdapter(credential_provider=provider),
            BROWSER: BrowserEngineAdapter(),
            SCRAPY: ScrapyEngineAdapter(),
        }

    def resolve(self, engine: str) -> EngineAdapter:
        try:
            return self._adapters[engine]
        except KeyError:
            raise UnknownEngineError(f"no engine adapter registered for: {engine!r}") from None
