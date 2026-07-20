from __future__ import annotations

import os
import base64
import binascii
import secrets
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask

from app.models import (
    ConnectionTestRequest,
    DocumentationRefreshRequest,
    ExportRequest,
    GraphQLRunRequest,
    OpenApiImportRequest,
    ApiRunResponse,
    RestConnectionTestRequest,
    RestRunRequest,
)
from app.services.exporter import create_csv, create_json, create_xlsx, safe_filename
from app.services.graphql_client import build_request_headers, execute_paginated
from app.services.openapi_importer import fetch_openapi_templates
from app.services.api_documentation import (
    generated_documentation,
    load_documentation,
    refresh_documentation,
    save_documentation_record,
)
from app.services.rest_client import execute_rest_paginated, resolve_endpoint_parameters
from app.services.saved_query_groups import load_saved_query_groups, save_saved_query_groups
from app.services.saved_queries import load_saved_queries, save_saved_queries


app = FastAPI(title="Ossy's API Hub", version="0.2.0")


@app.middleware("http")
async def require_app_authentication(request, call_next):
    expected_password = os.getenv("APP_PASSWORD", "")
    if (
        not expected_password
        or not request.url.path.startswith("/api/")
        or request.url.path == "/api/health"
    ):
        return await call_next(request)

    expected_username = os.getenv("APP_USERNAME", "ossy")
    authorization = request.headers.get("Authorization", "")
    username = password = ""
    if authorization.startswith("Basic "):
        try:
            decoded = base64.b64decode(authorization[6:], validate=True).decode("utf-8")
            username, password = decoded.split(":", 1)
        except (binascii.Error, ValueError, UnicodeDecodeError):
            pass

    if not (
        secrets.compare_digest(username, expected_username)
        and secrets.compare_digest(password, expected_password)
    ):
        return JSONResponse(
            status_code=401,
            content={"detail": "Sign in to Ossy's API Hub"},
            headers={"WWW-Authenticate": 'Basic realm="Ossys API Hub"'},
        )
    return await call_next(request)

frontend_origins = [origin.strip() for origin in os.getenv("FRONTEND_ORIGINS", "http://localhost:5173").split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "graphql-hub-api"}


@app.get("/api/saved-queries")
async def get_saved_queries() -> list[dict[str, Any]]:
    try:
        return load_saved_queries()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.put("/api/saved-queries")
async def put_saved_queries(queries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        return save_saved_queries(queries)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not save queries: {exc}") from exc


def _saved_query(query_id: str) -> dict[str, Any]:
    query = next((item for item in load_saved_queries() if str(item.get("id")) == query_id), None)
    if query is None:
        raise HTTPException(status_code=404, detail="Saved query was not found")
    return query


@app.get("/api/saved-queries/{query_id}/documentation")
async def get_query_documentation(query_id: str) -> dict[str, Any]:
    try:
        documentation = load_documentation()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return documentation.get(query_id) or generated_documentation(_saved_query(query_id))


@app.put("/api/saved-queries/{query_id}/documentation")
async def put_query_documentation(query_id: str, documentation: dict[str, Any]) -> dict[str, Any]:
    _saved_query(query_id)
    record = {**documentation, "queryId": query_id}
    try:
        return save_documentation_record(record)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"Could not save documentation: {exc}") from exc


@app.post("/api/saved-queries/{query_id}/documentation/refresh")
async def refresh_query_documentation(
    query_id: str,
    request: DocumentationRefreshRequest,
) -> dict[str, Any]:
    try:
        return await refresh_documentation(
            _saved_query(query_id),
            request.bearer_token,
            request.timeout_seconds,
            request.verify_ssl,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        message = exc.response.text if isinstance(exc, httpx.HTTPStatusError) else str(exc)
        raise HTTPException(status_code=502, detail=message) from exc


@app.get("/api/saved-query-groups")
async def get_saved_query_groups() -> list[str]:
    try:
        return load_saved_query_groups()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.put("/api/saved-query-groups")
async def put_saved_query_groups(groups: list[str]) -> list[str]:
    try:
        return save_saved_query_groups(groups)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Could not save query groups: {exc}") from exc


@app.post("/api/test-connection")
async def test_connection(request: ConnectionTestRequest) -> dict[str, object]:
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(request.timeout_seconds),
            verify=request.verify_ssl,
            follow_redirects=True,
        ) as client:
            response = await client.post(
                str(request.endpoint),
                headers=build_request_headers(request.headers, request.bearer_token),
                json={"query": "query GraphQLHubConnectionTest { __typename }", "variables": {}},
            )
        try:
            body = response.json()
        except ValueError:
            body = None
        ok = response.is_success and isinstance(body, dict)
        return {
            "ok": ok,
            "status_code": response.status_code,
            "message": (
                "Connection successful"
                if ok
                else "Endpoint did not return a JSON object"
                if response.is_success
                else "Endpoint returned an error"
            ),
            "response": body,
        }
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/run", response_model=ApiRunResponse)
async def run_query(request: GraphQLRunRequest) -> ApiRunResponse:
    return await execute_paginated(request)


@app.post("/api/rest/test-connection")
async def test_rest_connection(request: RestConnectionTestRequest) -> dict[str, object]:
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(request.timeout_seconds),
            verify=request.verify_ssl,
            follow_redirects=True,
        ) as client:
            headers = build_request_headers(request.headers, request.bearer_token)
            payload: dict[str, object] = {}
            if request.method != "GET" and request.body:
                if request.body_format == "form":
                    if not any(name.lower() == "content-type" for name in request.headers):
                        headers.pop("Content-Type", None)
                    payload["data"] = request.body or {}
                else:
                    payload["json"] = request.body or {}
            endpoint, query_params = resolve_endpoint_parameters(
                str(request.endpoint), request.query_params
            )
            response = await client.request(
                request.method,
                endpoint,
                headers=headers,
                params=query_params,
                **payload,
            )
        try:
            body = response.json()
        except ValueError:
            body = None
        ok = response.is_success and body is not None
        return {
            "ok": ok,
            "status_code": response.status_code,
            "message": (
                "Connection successful"
                if ok
                else "Endpoint did not return JSON"
                if response.is_success
                else "Endpoint returned an error"
            ),
            "response": body,
        }
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/rest/run", response_model=ApiRunResponse)
async def run_rest_query(request: RestRunRequest) -> ApiRunResponse:
    return await execute_rest_paginated(request)


@app.post("/api/openapi/templates")
async def import_openapi_templates(request: OpenApiImportRequest) -> list[dict[str, object]]:
    try:
        return await fetch_openapi_templates(str(request.url))
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/export")
async def export_report(request: ExportRequest):
    if request.format == "csv":
        content = create_csv(request.records)
        return Response(
            content=content,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{safe_filename(request.filename, "csv")}"'},
        )
    if request.format == "json":
        content = create_json(request.records)
        return Response(
            content=content,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{safe_filename(request.filename, "json")}"'},
        )

    path = create_xlsx(
        request.records,
        request.query,
        request.variables,
        request.endpoint,
        request.run_summary,
        request.errors,
    )
    return FileResponse(
        path,
        filename=safe_filename(request.filename, "xlsx"),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        background=BackgroundTask(path.unlink, missing_ok=True),
    )


frontend_dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=frontend_dist, html=True), name="frontend")
