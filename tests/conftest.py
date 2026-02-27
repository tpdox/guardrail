"""Shared test fixtures for guardrail tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from guardrail.manifest import Manifest

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def two_models_manifest() -> Manifest:
    """Load the two_models test fixture manifest."""
    manifest_path = FIXTURES_DIR / "manifests" / "two_models.json"
    with open(manifest_path) as f:
        data = json.load(f)
    return Manifest(data)


@pytest.fixture
def two_models_data() -> dict:
    """Load raw manifest data."""
    manifest_path = FIXTURES_DIR / "manifests" / "two_models.json"
    with open(manifest_path) as f:
        return json.load(f)
