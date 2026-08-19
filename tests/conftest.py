"""Shared fixtures."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from pipeline.config.settings import PATHS

REPO_ROOT = PATHS.root


@pytest.fixture
def replay_root() -> Path:
    """The committed replay fixtures used by the deterministic gate."""
    return PATHS.replay_fixtures


def make_client_factory(
    handler: Callable[[httpx.Request], httpx.Response],
) -> Callable[[], httpx.Client]:
    """Build a LiveFetcher client factory backed by an in-memory transport."""

    def factory() -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler))

    return factory
