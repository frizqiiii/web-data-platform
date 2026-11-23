import pytest
from worker.engines.browser.engine import BrowserEngineAdapter
from worker.engines.http.engine import HttpEngineAdapter
from worker.engines.resolver import BROWSER, HTTP, SCRAPY, EngineResolver, UnknownEngineError
from worker.engines.scrapy.engine import ScrapyEngineAdapter


def test_resolver_dispatches_http() -> None:
    resolver = EngineResolver()
    assert isinstance(resolver.resolve(HTTP), HttpEngineAdapter)


def test_resolver_dispatches_browser() -> None:
    resolver = EngineResolver()
    assert isinstance(resolver.resolve(BROWSER), BrowserEngineAdapter)


def test_resolver_dispatches_scrapy() -> None:
    resolver = EngineResolver()
    assert isinstance(resolver.resolve(SCRAPY), ScrapyEngineAdapter)


def test_resolver_rejects_unknown_engine() -> None:
    resolver = EngineResolver()
    with pytest.raises(UnknownEngineError):
        resolver.resolve("NOT_A_REAL_ENGINE")


def test_resolver_reuses_the_same_adapter_instances() -> None:
    """Not a per-execution object — resolving the same engine twice
    should return the same adapter instance, not construct a new
    one each time."""
    resolver = EngineResolver()
    assert resolver.resolve(HTTP) is resolver.resolve(HTTP)
