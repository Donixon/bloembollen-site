from __future__ import annotations

import io
import struct
import zlib

from fastapi.testclient import TestClient
from PIL import Image

from app.config import Settings
from app.main import create_app
from tests.conftest import post_data


def create_post(client: TestClient, jpeg_bytes: bytes, **overrides: str):
    return client.post(
        "/api/posts",
        data=post_data(**overrides),
        files={"photo": ("bol.jpg", jpeg_bytes, "image/jpeg")},
    )


def test_cache_control_headers(client: TestClient, jpeg_bytes: bytes) -> None:
    for path in ("/", "/js/app.js", "/css/style.css"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-cache"

    post = create_post(client, jpeg_bytes).json()
    media = client.get(post["photo_url"])
    assert media.status_code == 200
    assert media.headers["cache-control"] == "public, max-age=31536000, immutable"

    api = client.get("/api/health")
    assert api.status_code == 200
    assert "cache-control" not in api.headers


def test_post_get_and_media(client: TestClient, jpeg_bytes: bytes) -> None:
    response = create_post(client, jpeg_bytes)
    assert response.status_code == 201
    post = response.json()
    assert post == {
        "id": 1,
        "name": "Tante Riet",
        "message": "Eindelijk geplant!",
        "lat": 52.37,
        "lon": 4.9,
        "photo_url": "/media/photos/1.jpg",
        "thumb_url": "/media/thumbs/1.jpg",
        "created_at": post["created_at"],
    }
    assert post["created_at"].endswith("Z")
    assert client.get("/api/posts/1").json() == post
    assert client.get("/api/posts").json() == {
        "items": [post],
        "next_before_id": None,
    }
    assert client.get("/api/posts/map").json() == [
        {"id": 1, "name": "Tante Riet", "lat": 52.37, "lon": 4.9, "thumb_url": "/media/thumbs/1.jpg"}
    ]
    media = client.get(post["photo_url"])
    assert media.status_code == 200
    assert media.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_coordinates_must_be_in_netherlands(client: TestClient, jpeg_bytes: bytes) -> None:
    response = create_post(client, jpeg_bytes, lat="49.0")
    assert response.status_code == 422
    assert response.json() == {"detail": "De locatie moet binnen Nederland liggen."}


def test_invalid_and_too_large_photo(client: TestClient) -> None:
    invalid = client.post(
        "/api/posts",
        data=post_data(),
        files={"photo": ("nep.jpg", b"geen foto", "image/jpeg")},
    )
    assert invalid.status_code == 422
    assert invalid.json()["detail"].startswith("Gebruik een geldige")

    too_large = client.post(
        "/api/posts",
        data=post_data(),
        files={"photo": ("groot.jpg", b"x" * (1024 * 1024 + 1), "image/jpeg")},
    )
    assert too_large.status_code == 413
    assert too_large.json() == {"detail": "De foto mag maximaal 1 MB groot zijn."}


def test_decompression_bomb_is_rejected_without_saving(
    client: TestClient, settings: Settings
) -> None:
    def png_chunk(chunk_type: bytes, data: bytes) -> bytes:
        checksum = zlib.crc32(chunk_type + data)
        return struct.pack(">I", len(data)) + chunk_type + data + struct.pack(">I", checksum)

    ihdr = struct.pack(">IIBBBBB", 20_000, 20_000, 8, 2, 0, 0, 0)
    oversized_dimensions = (
        b"\x89PNG\r\n\x1a\n"
        + png_chunk(b"IHDR", ihdr)
        + png_chunk(b"IDAT", zlib.compress(b"\x00"))
        + png_chunk(b"IEND", b"")
    )

    response = client.post(
        "/api/posts",
        data=post_data(),
        files={"photo": ("groot.png", oversized_dimensions, "image/png")},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "De foto heeft te grote pixelafmetingen."}
    assert client.get("/api/posts").json()["items"] == []
    assert list(settings.photos_dir.iterdir()) == []
    assert list(settings.thumbs_dir.iterdir()) == []


def test_honeypot_returns_silent_success_without_saving(
    client: TestClient, jpeg_bytes: bytes
) -> None:
    response = create_post(client, jpeg_bytes, website="spam")
    assert response.status_code == 201
    assert response.content == b""
    assert client.get("/api/posts").json()["items"] == []


def test_delete_requires_token_and_removes_files(
    client: TestClient, jpeg_bytes: bytes
) -> None:
    post = create_post(client, jpeg_bytes).json()
    assert client.delete("/api/posts/1").status_code == 403
    assert client.delete(
        "/api/posts/1", headers={"X-Admin-Token": "fout"}
    ).status_code == 403
    response = client.delete(
        "/api/posts/1", headers={"X-Admin-Token": "test-token"}
    )
    assert response.status_code == 204
    assert client.get(post["photo_url"]).status_code == 404
    assert client.get("/api/posts/1").status_code == 404


def test_delete_disabled_without_admin_token(settings: Settings) -> None:
    disabled = Settings(
        data_dir=settings.data_dir,
        admin_token=None,
        coord_decimals=2,
        max_upload_mb=1,
    )
    with TestClient(create_app(disabled)) as client:
        response = client.delete("/api/posts/1", headers={"X-Admin-Token": "iets"})
    assert response.status_code == 403
    assert response.json() == {"detail": "Verwijderen is uitgeschakeld."}


def test_pagination(client: TestClient, jpeg_bytes: bytes) -> None:
    for number in range(3):
        response = create_post(client, jpeg_bytes, name=f"Naam {number}")
        assert response.status_code == 201
    first = client.get("/api/posts?limit=2").json()
    assert [post["id"] for post in first["items"]] == [3, 2]
    assert first["next_before_id"] == 2
    second = client.get(f"/api/posts?limit=2&before_id={first['next_before_id']}").json()
    assert [post["id"] for post in second["items"]] == [1]
    assert second["next_before_id"] is None


def test_exif_is_applied_and_stripped(client: TestClient) -> None:
    source = io.BytesIO()
    image = Image.new("RGB", (40, 20), "red")
    exif = Image.Exif()
    exif[274] = 6
    exif[315] = "Privenaam"
    image.save(source, "JPEG", exif=exif)

    post = create_post(client, source.getvalue()).json()
    stored = client.get(post["photo_url"]).content
    with Image.open(io.BytesIO(stored)) as result:
        assert result.size == (20, 40)
        assert len(result.getexif()) == 0


def test_gps_comment_is_stripped_from_photo_and_thumbnail(client: TestClient) -> None:
    source = io.BytesIO()
    Image.new("RGB", (40, 20), "red").save(source, "JPEG")
    comment = b"GPSLatitude=52.371230;GPSLongitude=4.901230"
    jpeg = source.getvalue()
    jpeg_with_comment = (
        jpeg[:2] + b"\xff\xfe" + struct.pack(">H", len(comment) + 2) + comment + jpeg[2:]
    )

    response = create_post(client, jpeg_with_comment)
    assert response.status_code == 201

    for url_key in ("photo_url", "thumb_url"):
        stored = client.get(response.json()[url_key]).content
        assert comment not in stored
        with Image.open(io.BytesIO(stored)) as result:
            assert "comment" not in result.info


def test_health_and_dutch_not_found(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"ok": True}
    response = client.get("/api/bestaat-niet")
    assert response.status_code == 404
    assert response.json() == {"detail": "Niet gevonden."}


def test_public_documentation_pages_are_disabled(client: TestClient) -> None:
    assert client.get("/").status_code == 200
    assert client.get("/api/health").status_code == 200
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404


def test_framework_errors_are_dutch(client: TestClient) -> None:
    malformed_multipart = client.post(
        "/api/posts",
        content=b"ongeldige multipart-inhoud",
        headers={"Content-Type": "multipart/form-data"},
    )
    assert malformed_multipart.status_code == 400
    assert malformed_multipart.json() == {
        "detail": "De multipart-aanvraag mist een boundary."
    }

    missing_media = client.get("/media/photos/absent.jpg")
    assert missing_media.status_code == 404
    assert missing_media.json() == {"detail": "Niet gevonden."}

    wrong_method = client.put("/api/posts")
    assert wrong_method.status_code == 405
    assert wrong_method.json() == {"detail": "Deze methode is niet toegestaan."}


def test_malformed_multipart_body_error_is_dutch(client: TestClient) -> None:
    response = client.post(
        "/api/posts",
        content=b"bad data",
        headers={"Content-Type": "multipart/form-data; boundary=x"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "De multipart-aanvraag kon niet worden verwerkt."
    }


def test_multipart_field_without_name_error_is_dutch(client: TestClient) -> None:
    response = client.post(
        "/api/posts",
        content=(
            b"--x\r\n"
            b"Content-Disposition: form-data\r\n"
            b"\r\n"
            b"x\r\n"
            b"--x--\r\n"
        ),
        headers={"Content-Type": "multipart/form-data; boundary=x"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Een multipart-veld mist een naam."}


def test_oversized_multipart_field_error_is_dutch(client: TestClient) -> None:
    response = client.post(
        "/api/posts",
        content=(
            b"--x\r\n"
            b'Content-Disposition: form-data; name="message"\r\n'
            b"\r\n"
            + b"x" * (1024 * 1024 + 1)
            + b"\r\n--x--\r\n"
        ),
        headers={"Content-Type": "multipart/form-data; boundary=x"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Een multipart-veld mag maximaal 1 MB groot zijn."
    }


def test_custom_not_found_detail_is_preserved(client: TestClient) -> None:
    response = client.get("/api/posts/1")
    assert response.status_code == 404
    assert response.json() == {"detail": "Deze bijdrage bestaat niet."}
