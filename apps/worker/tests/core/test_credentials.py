import pytest
from worker.core.credentials import NullCredentialProvider


@pytest.mark.asyncio
async def test_null_credential_provider_always_returns_none() -> None:
    provider = NullCredentialProvider()
    assert await provider.get_credential("anything") is None
    assert await provider.get_credential("") is None
