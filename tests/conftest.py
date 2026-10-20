from __future__ import annotations

import io
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        admin_token="test-token",
        coord_decimals=2,
        max_upload_mb=1,
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def jpeg_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (800, 600), "green").save(output, "JPEG")
    return output.getvalue()


def post_data(**overrides: str) -> dict[str, str]:
    values = {
        "name": "Tante Riet",
        "message": "Eindelijk geplant!",
        "lat": "52.37123",
        "lon": "4.90123",
        "website": "",
    }
    values.update(overrides)
    return values
