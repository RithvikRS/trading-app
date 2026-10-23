"""Serve only the separate protected build, from a fixed local directory."""

import re
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import Response

BUILD = Path(__file__).resolve().parents[2] / "frontend/workspace/dist"
CONTENT_POLICY = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; "
    "object-src 'none'; frame-ancestors 'none'"
)
MEDIA = {".js": "text/javascript", ".css": "text/css", ".woff2": "font/woff2"}


def routes() -> APIRouter:
    # Read the immutable public assets once. Never resolve a request to a filesystem path.
    # A missing/incomplete build fails startup; the demo directory is never consulted.
    files: dict[str, tuple[bytes, str]] = {}
    if BUILD.is_symlink() or not BUILD.is_dir():
        raise ValueError("Build the protected frontend before enabling it.")
    for path in BUILD.rglob("*"):
        if path.is_symlink() or not path.resolve().is_relative_to(BUILD.resolve()):
            raise ValueError("Invalid protected build.")
        if not path.is_file():
            continue
        relative = path.relative_to(BUILD).as_posix()
        if relative == "index.html":
            name, media = "/", "text/html"
        elif re.fullmatch(r"assets/[A-Za-z0-9_-]+\.(js|css|woff2)", relative):
            name, media = f"/{relative}", MEDIA[path.suffix]
        else:
            raise ValueError("Unexpected protected build file.")
        if path.stat().st_size > 2_000_000:
            raise ValueError("Protected asset exceeds the size limit.")
        files[name] = (path.read_bytes(), media)
    if "/" not in files or not any(name.endswith(".js") for name in files):
        raise ValueError("Incomplete protected build.")
    if sum(len(body) for body, _ in files.values()) > 8_000_000:
        raise ValueError("Protected build exceeds the size limit.")
    router = APIRouter()

    @router.get("/")
    @router.get("/assets/{asset}")
    def asset(request: Request) -> Response:
        entry = files.get(request.url.path)
        if entry is None or request.url.query:
            raise HTTPException(404)
        request.state.protected_asset = True
        body, media = entry
        return Response(body, media_type=media)

    return router
