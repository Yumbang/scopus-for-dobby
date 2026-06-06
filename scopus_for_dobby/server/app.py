"""FastAPI app exposing the scopus-for-dobby core over HTTP.

Endpoints mirror :mod:`scopus_for_dobby.core.article_db` one-to-one. The
daemon process holds the only DuckDB connection — every read and write
funnels through here. Bind to 127.0.0.1; this is a personal-machine tool.

Run with::

    scopus-for-dobby serve --host 127.0.0.1 --port 8765

or programmatically::

    from scopus_for_dobby.server import build_app
    app = build_app()
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import signal
import time
from typing import Any

from scopus_for_dobby.core import article_db as adb

logger = logging.getLogger(__name__)


def _err(exc: Exception, status: int = 400) -> dict:
    return {"error": str(exc), "type": type(exc).__name__, "status": status}


def build_app(idle_timeout: float | None = None):
    """Build the FastAPI app. Imported lazily so FastAPI is an optional dep.

    ``idle_timeout`` (seconds) enables a background watchdog that sends
    SIGTERM to the current process when no request has arrived within
    the window. Used by the lazy-spawn daemon (``serve --background``)
    so an idle machine doesn't carry a forgotten uvicorn process. Pass
    ``None`` (default) for tests and the foreground ``serve`` command.
    """
    try:
        from fastapi import Body, FastAPI, HTTPException
        from fastapi.responses import JSONResponse, StreamingResponse
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            "FastAPI not installed. Install with `pip install scopus-for-dobby[gui-support]`."
        ) from e

    app = FastAPI(title="scopus-for-dobby", version="1.0.0")
    # ``last`` is the monotonic timestamp of the most recent activity;
    # ``streams`` counts currently-connected SSE clients. The watchdog
    # only kills the daemon when both are idle (no recent request AND no
    # live stream), so a long-lived /events/stream keeps us alive.
    activity = {"last": time.monotonic(), "streams": 0}

    def _touch() -> None:
        activity["last"] = time.monotonic()

    @app.middleware("http")
    async def _track_activity(request, call_next):
        _touch()
        try:
            return await call_next(request)
        finally:
            # Refresh on completion too, so requests that outlive the
            # idle window (e.g. a closing SSE stream) don't go stale.
            _touch()

    if idle_timeout and idle_timeout > 0:

        @app.on_event("startup")
        async def _start_idle_watchdog():
            async def _watch():
                check = max(5.0, idle_timeout / 4)
                while True:
                    await asyncio.sleep(check)
                    if activity["streams"] > 0:
                        continue
                    if time.monotonic() - activity["last"] >= idle_timeout:
                        os.kill(os.getpid(), signal.SIGTERM)
                        return

            asyncio.create_task(_watch())

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "fts_available": adb.fts_available(),
            "db_path": str(adb.DB_PATH),
        }

    # ── Articles ─────────────────────────────────────────────────────────────
    @app.get("/articles")
    def list_articles(
        tag: str | None = None,
        collection: str | None = None,
        query: str | None = None,
        sort: str = "added",
        limit: int = 50,
    ):
        return adb.list_articles(
            tag=tag, collection=collection, query=query, sort=sort, limit=limit
        )

    @app.get("/articles/{eid}")
    def get_article(eid: str):
        try:
            return adb.get_article(eid)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    @app.post("/articles")
    def add_articles(body: dict = Body(...)):
        entries = body.get("entries") or []
        tags = body.get("tags")
        collection = body.get("collection")
        return adb.add_entries(entries, tags=tags, collection=collection)

    @app.delete("/articles")
    def remove_articles(body: dict = Body(...)):
        return adb.remove_entries(body.get("eids", []))

    # ── Search ───────────────────────────────────────────────────────────────
    @app.get("/search/fts")
    def search_fts(query: str, limit: int = 50):
        try:
            return adb.search_articles_fts(query, limit=limit)
        except RuntimeError:
            return adb.search_articles_like(query, limit=limit)

    @app.get("/search/like")
    def search_like(query: str, limit: int = 50):
        return adb.search_articles_like(query, limit=limit)

    # ── Tags & notes ─────────────────────────────────────────────────────────
    @app.post("/articles/tag")
    def tag(body: dict = Body(...)):
        return adb.tag_articles(body.get("eids", []), body.get("tags", []))

    @app.post("/articles/untag")
    def untag(body: dict = Body(...)):
        return adb.untag_articles(body.get("eids", []), body.get("tags", []))

    @app.post("/articles/{eid}/note")
    def set_note(eid: str, body: dict = Body(...)):
        try:
            return adb.set_note(eid, body.get("note", ""))
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e)) from e

    # ── Collections ──────────────────────────────────────────────────────────
    @app.get("/collections")
    def list_collections():
        return adb.list_collections()

    @app.post("/collections")
    def create_collection(body: dict = Body(...)):
        return adb.create_collection(body["name"])

    @app.delete("/collections/{name}")
    def delete_collection(name: str):
        return adb.delete_collection(name)

    @app.post("/collections/{name}/articles")
    def add_to_collection(name: str, body: dict = Body(...)):
        return adb.add_to_collection(name, body.get("eids", []))

    @app.delete("/collections/{name}/articles")
    def remove_from_collection(name: str, body: dict = Body(...)):
        return adb.remove_from_collection(name, body.get("eids", []))

    @app.post("/collections/merge")
    def merge_collections(body: dict = Body(...)):
        return adb.merge_collections(body["src"], body["dst"])

    @app.post("/collections/rename")
    def rename_collection(body: dict = Body(...)):
        return adb.rename_collection(body["old"], body["new"])

    # ── Authors ──────────────────────────────────────────────────────────────
    @app.get("/authors")
    def list_authors(query: str | None = None, sort: str = "papers", limit: int = 50):
        return adb.list_authors(query=query, sort=sort, limit=limit)

    @app.get("/authors/{auid}")
    def get_author(auid: str):
        return adb.get_author(auid)

    @app.post("/authors/{auid}/note")
    def set_author_note(auid: str, body: dict = Body(...)):
        return adb.set_author_note(auid, body.get("note", ""))

    @app.get("/authors/{auid}/coauthors")
    def find_coauthors(auid: str):
        return adb.find_coauthors(auid)

    @app.post("/authors/{auid}/fetch")
    def fetch_author(auid: str):
        try:
            return adb.fetch_author_profile(auid)
        except Exception as e:
            # Don't leak upstream Scopus response bodies to the client.
            # Log the full error server-side; return a sanitized detail,
            # surfacing only an HTTP status code if we can extract one.
            logger.exception("Author fetch failed for %s", auid)
            m = re.search(r"HTTP (\d+)", str(e))
            detail = (
                f"Scopus API request failed (status {m.group(1)})"
                if m
                else "Scopus API request failed"
            )
            raise HTTPException(status_code=502, detail=detail) from e

    # ── Stats / FTS ──────────────────────────────────────────────────────────
    @app.get("/stats")
    def stats():
        return adb.stats()

    @app.post("/fts/rebuild")
    def rebuild_fts():
        return adb.rebuild_fts()

    # ── Events ───────────────────────────────────────────────────────────────
    @app.get("/events")
    def list_events(since: int = 0, limit: int = 500):
        conn = adb._get_conn()
        rows = conn.execute(
            "SELECT id, ts, kind, entity_type, entity_id, payload "
            "FROM events WHERE id > ? ORDER BY id ASC LIMIT ?",
            [since, limit],
        ).fetchall()
        return {
            "events": [
                {
                    "id": r[0],
                    "ts": str(r[1]) if r[1] is not None else None,
                    "kind": r[2],
                    "entity_type": r[3],
                    "entity_id": r[4],
                    "payload": json.loads(r[5]) if r[5] else {},
                }
                for r in rows
            ],
            "max_id": rows[-1][0] if rows else since,
        }

    @app.get("/events/stream")
    async def stream_events(since: int = 0):
        async def gen():
            cursor = since
            activity["streams"] += 1
            try:
                yield "retry: 2000\n\n"
                while True:
                    # Keep the daemon alive while a client is connected: a
                    # streaming response otherwise never re-enters the
                    # middleware, so the watchdog would see us as idle.
                    _touch()
                    conn = adb._get_conn()
                    rows = conn.execute(
                        "SELECT id, kind, entity_type, entity_id, payload "
                        "FROM events WHERE id > ? ORDER BY id ASC LIMIT 200",
                        [cursor],
                    ).fetchall()
                    for r in rows:
                        cursor = r[0]
                        try:
                            data = json.loads(r[4]) if r[4] else {}
                        except (ValueError, TypeError):
                            # One corrupted payload row must not kill the
                            # stream; skip it and keep going.
                            logger.warning("Skipping event %s with unparseable payload", r[0])
                            continue
                        payload: dict[str, Any] = {
                            "id": r[0],
                            "kind": r[1],
                            "entity_type": r[2],
                            "entity_id": r[3],
                            "payload": data,
                        }
                        yield f"id: {r[0]}\ndata: {json.dumps(payload)}\n\n"
                    # Periodic comment doubles as an SSE keepalive and lets
                    # the client notice a dropped connection promptly.
                    yield ": keepalive\n\n"
                    await asyncio.sleep(0.5)
            finally:
                activity["streams"] -= 1

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.exception_handler(ValueError)
    async def value_error_handler(request, exc):
        return JSONResponse(status_code=400, content=_err(exc, 400))

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request, exc):
        # Catch-all: log the full traceback server-side but never leak
        # internal details (messages, stack frames) to the client.
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"error": "Internal server error", "status": 500},
        )

    return app
