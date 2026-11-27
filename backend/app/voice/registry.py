from functools import lru_cache

from app.core.config import get_settings
from app.voice.base import VoiceProvider
from app.voice.providers.mock import MockVoiceProvider

_overrides: dict[str, VoiceProvider] = {}


@lru_cache
def _mock() -> MockVoiceProvider:
    return MockVoiceProvider(get_settings().mock_webhook_secret)


def get_provider(name: str | None = None, api_key: str | None = None) -> VoiceProvider:
    """Return the provider adapter. `api_key` selects tenant-scoped Retell credentials."""
    name = name or get_settings().voice_provider
    if name in _overrides:
        return _overrides[name]
    if name == "mock":
        if get_settings().environment == "production":
            raise RuntimeError("Mock provider disabled in production")
        return _mock()
    if name == "retell":
        from app.voice.providers.retell import RetellProvider

        return RetellProvider(api_key or get_settings().retell_api_key)
    raise ValueError(f"Unknown provider {name}")


def override_provider(name: str, provider: VoiceProvider | None) -> None:
    """Test hook."""
    if provider is None:
        _overrides.pop(name, None)
    else:
        _overrides[name] = provider
