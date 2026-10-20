from __future__ import annotations

import hmac
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import Settings
from app.database import connect, initialize_database, row_to_post
from app.images import (
    ImageDimensionsTooLarge,
    ImageTooLarge,
    InvalidImage,
    prepare_images,
    remove_files,
)
from app.rate_limit import PostRateLimiter

STATIC_DIR = Path(__file__).parent / "static"

FRAMEWORK_FOUTEN = {
    "Missing boundary in multipart.": "De multipart-aanvraag mist een boundary.",
    "There was an error parsing the body": (
        "De multipart-aanvraag kon niet worden verwerkt."
    ),
    'The Content-Disposition header field "name" must be provided.': (
        "Een multipart-veld mist een naam."
    ),
    "Part exceeded maximum size of 1024KB.": (
        "Een multipart-veld mag maximaal 1 MB groot zijn."
    ),
    "Not Found": "Niet gevonden.",
    "Method Not Allowed": "Deze methode is niet toegestaan.",
}


def _api_error(status_code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail=detail)


def _http_detail(exc: StarletteHTTPException) -> object:
    if isinstance(exc.detail, str) and exc.detail in FRAMEWORK_FOUTEN:
        return FRAMEWORK_FOUTEN[exc.detail]
    if isinstance(exc, HTTPException):
        return exc.detail
    return "De aanvraag kon niet worden verwerkt."


def _parse_coordinate(value: str | None, label: str) -> float:
    if value is None or value.strip() == "":
        raise _api_error(422, f"{label} is verplicht.")
    try:
        return float(value)
    except ValueError as exc:
        raise _api_error(422, f"{label} moet een geldig getal zijn.") from exc


def _validate_text(name: str | None, message: str | None) -> tuple[str, str]:
    clean_name = (name or "").strip()
    clean_message = (message or "").strip()
    if not clean_name:
        raise _api_error(422, "Naam is verplicht.")
    if len(clean_name) > 60:
        raise _api_error(422, "Naam mag maximaal 60 tekens bevatten.")
    if len(clean_message) > 500:
        raise _api_error(422, "Bericht mag maximaal 500 tekens bevatten.")
    return clean_name, clean_message


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    limiter = PostRateLimiter()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        settings.photos_dir.mkdir(parents=True, exist_ok=True)
        settings.thumbs_dir.mkdir(parents=True, exist_ok=True)
        initialize_database(settings.database_path)
        yield

    application = FastAPI(
        title="Bloembollen",
        docs_url=None,
        redoc_url=None,
        lifespan=lifespan,
    )

    @application.exception_handler(RequestValidationError)
    async def validation_error(_: Request, __: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"detail": "De aangeleverde gegevens zijn niet geldig."},
        )

    @application.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": _http_detail(exc)},
        )

    @application.middleware("http")
    async def media_cache(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/media/") and response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif not path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @application.get("/api/health")
    def health() -> dict[str, bool]:
        return {"ok": True}

    @application.post("/api/posts", status_code=201, response_model=None)
    def create_post(
        request: Request,
        name: str | None = Form(default=None),
        message: str | None = Form(default=None),
        lat: str | None = Form(default=None),
        lon: str | None = Form(default=None),
        photo: UploadFile | None = File(default=None),
        website: str | None = Form(default=None),
    ) -> dict[str, object] | Response:
        if (website or "").strip():
            return Response(status_code=201)

        clean_name, clean_message = _validate_text(name, message)
        latitude = _parse_coordinate(lat, "Breedtegraad")
        longitude = _parse_coordinate(lon, "Lengtegraad")
        if not 50.7 <= latitude <= 53.7 or not 3.2 <= longitude <= 7.3:
            raise _api_error(422, "De locatie moet binnen Nederland liggen.")
        if photo is None:
            raise _api_error(422, "Een foto is verplicht.")

        client_ip = request.client.host if request.client else "onbekend"
        if not limiter.allow(client_ip):
            raise _api_error(
                429, "Je hebt te veel foto's geplaatst. Probeer het later opnieuw."
            )

        try:
            temp_photo, temp_thumb = prepare_images(
                photo.file,
                settings.photos_dir,
                settings.thumbs_dir,
                settings.max_upload_mb * 1024 * 1024,
            )
        except ImageTooLarge as exc:
            raise _api_error(
                413,
                f"De foto mag maximaal {settings.max_upload_mb} MB groot zijn.",
            ) from exc
        except ImageDimensionsTooLarge as exc:
            raise _api_error(422, "De foto heeft te grote pixelafmetingen.") from exc
        except InvalidImage as exc:
            raise _api_error(
                422, "Gebruik een geldige JPEG-, PNG-, WebP- of HEIC-foto."
            ) from exc

        rounded_lat = round(latitude, settings.coord_decimals)
        rounded_lon = round(longitude, settings.coord_decimals)
        created_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        final_photo: Path | None = None
        final_thumb: Path | None = None
        try:
            with connect(settings.database_path) as connection:
                cursor = connection.execute(
                    """
                    INSERT INTO posts
                        (name, message, lat, lon, photo_url, thumb_url, created_at)
                    VALUES (?, ?, ?, ?, '', '', ?)
                    """,
                    (clean_name, clean_message, rounded_lat, rounded_lon, created_at),
                )
                post_id = int(cursor.lastrowid or 0)
                final_photo = settings.photos_dir / f"{post_id}.jpg"
                final_thumb = settings.thumbs_dir / f"{post_id}.jpg"
                os.replace(temp_photo, final_photo)
                os.replace(temp_thumb, final_thumb)
                photo_url = f"/media/photos/{post_id}.jpg"
                thumb_url = f"/media/thumbs/{post_id}.jpg"
                connection.execute(
                    "UPDATE posts SET photo_url = ?, thumb_url = ? WHERE id = ?",
                    (photo_url, thumb_url, post_id),
                )
                connection.commit()
        except Exception:
            remove_files(temp_photo, temp_thumb)
            if final_photo is not None:
                remove_files(final_photo)
            if final_thumb is not None:
                remove_files(final_thumb)
            raise

        return {
            "id": post_id,
            "name": clean_name,
            "message": clean_message,
            "lat": rounded_lat,
            "lon": rounded_lon,
            "photo_url": photo_url,
            "thumb_url": thumb_url,
            "created_at": created_at,
        }

    @application.get("/api/posts")
    def list_posts(
        limit: int = Query(default=24, ge=1, le=100),
        before_id: int | None = Query(default=None, ge=1),
    ) -> dict[str, object]:
        parameters: list[int] = []
        where = ""
        if before_id is not None:
            where = "WHERE id < ?"
            parameters.append(before_id)
        parameters.append(limit + 1)
        with connect(settings.database_path) as connection:
            rows = connection.execute(
                f"SELECT * FROM posts {where} ORDER BY id DESC LIMIT ?",  # noqa: S608
                parameters,
            ).fetchall()
        has_more = len(rows) > limit
        page = rows[:limit]
        return {
            "items": [row_to_post(row) for row in page],
            "next_before_id": page[-1]["id"] if has_more and page else None,
        }

    @application.get("/api/posts/map")
    def map_posts() -> list[dict[str, object]]:
        with connect(settings.database_path) as connection:
            rows = connection.execute(
                "SELECT id, name, lat, lon, thumb_url FROM posts ORDER BY id DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    @application.get("/api/posts/{post_id}")
    def get_post(post_id: int) -> dict[str, object]:
        with connect(settings.database_path) as connection:
            row = connection.execute(
                "SELECT * FROM posts WHERE id = ?", (post_id,)
            ).fetchone()
        if row is None:
            raise _api_error(404, "Deze bijdrage bestaat niet.")
        return row_to_post(row)

    @application.delete("/api/posts/{post_id}", status_code=204)
    def delete_post(
        post_id: int,
        x_admin_token: str | None = Header(default=None),
    ) -> Response:
        if settings.admin_token is None:
            raise _api_error(403, "Verwijderen is uitgeschakeld.")
        if x_admin_token is None or not hmac.compare_digest(
            x_admin_token, settings.admin_token
        ):
            raise _api_error(403, "De beheerderstoken is niet geldig.")

        with connect(settings.database_path) as connection:
            row = connection.execute(
                "SELECT id FROM posts WHERE id = ?", (post_id,)
            ).fetchone()
            if row is None:
                raise _api_error(404, "Deze bijdrage bestaat niet.")
            connection.execute("DELETE FROM posts WHERE id = ?", (post_id,))
            connection.commit()

        remove_files(
            settings.photos_dir / f"{post_id}.jpg",
            settings.thumbs_dir / f"{post_id}.jpg",
        )
        return Response(status_code=204)

    application.mount(
        "/media/photos",
        StaticFiles(directory=settings.photos_dir, check_dir=False),
        name="photos",
    )
    application.mount(
        "/media/thumbs",
        StaticFiles(directory=settings.thumbs_dir, check_dir=False),
        name="thumbs",
    )
    application.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
    return application


app = create_app()
