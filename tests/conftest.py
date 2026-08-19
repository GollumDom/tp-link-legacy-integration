"""Fixtures pour les tests exécutés dans Home Assistant."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from .sample_data import STATUS

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Rend `custom_components/tplink_legacy` visible par Home Assistant."""
    yield


@pytest.fixture
def mock_router():
    """Remplace le client réseau par un double, dans tous les modules qui l'utilisent."""
    router = AsyncMock()
    router.host = "192.168.11.1"
    router.get_status.return_value = STATUS
    router.get_info.return_value = STATUS["info"]
    router.disconnect.return_value = None

    with (
        patch("custom_components.tplink_legacy.coordinator.TpLinkRouter", return_value=router),
        patch("custom_components.tplink_legacy.config_flow.TpLinkRouter", return_value=router),
    ):
        yield router


@pytest.fixture
def no_discovery():
    """Neutralise la détection réseau pendant les tests."""
    with patch("custom_components.tplink_legacy.config_flow.discover", return_value=[]):
        yield
