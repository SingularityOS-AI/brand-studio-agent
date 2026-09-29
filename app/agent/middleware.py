"""HTTP middleware that writes the agent_actions audit trail (Block F, F-02).

Per docs/specs/F/plan.md §2 "Audit trail": every POST/PATCH/DELETE under the
pipeline endpoints (catalog, script, audiovisual, editing -- excluding
editing/internal -- and soul/generate) either updates the row a voice action
already created (X-Agent-Action-Id header) or inserts a `button` row.

Hard requirement from the piece: this middleware must NEVER block or change
the response, whether the agent_actions table doesn't exist yet (migration
014 not applied), Supabase is unreachable, or anything else goes wrong.
Every failure here is logged and swallowed.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.agent.store import create_action, update_action
from app.auth.supabase_auth import supabase_auth
from app.guard import guard

logger = logging.getLogger(__name__)

_EXCLUDED_PREFIXES = ("/api/editing/internal",)
_AUDITED_EXACT = ("/api/soul/generate",)

# Order matters: /api/editing/internal is excluded above, so checking
# "/api/editing" as a prefix here is safe (the exclusion is checked first).
_STEP_BY_PREFIX = (
    ("/api/catalog", "catalog"),
    ("/api/script", "script"),
    ("/api/audiovisual", "audiovisual"),
    ("/api/editing", "editing"),
    ("/api/soul/generate", "brand_soul"),
)

_AUDITED_METHODS = ("POST", "PATCH", "DELETE")

# Job-creating responses are tiny JSON ({"job": {...}}); anything bigger is not
# worth buffering just to read a job id.
_MAX_BODY_BYTES = 256 * 1024


def _is_audited_path(path: str) -> bool:
    if any(path.startswith(p) for p in _EXCLUDED_PREFIXES):
        return False
    if path in _AUDITED_EXACT:
        return True
    return any(path.startswith(prefix) for prefix, _ in _STEP_BY_PREFIX)


def _step_for_path(path: str) -> str:
    for prefix, step in _STEP_BY_PREFIX:
        if path == prefix or path.startswith(prefix):
            return step
    return "global"


def _route_template(request: Request) -> str:
    """Best-effort path template (e.g. "/api/script/{idea_id}/lock") for the
    matched route. Falls back to the raw path if routing info isn't available."""
    route = request.scope.get("route")
    path_template = getattr(route, "path", None)
    return path_template or request.url.path


def _extract_idea_id(request: Request) -> str | None:
    """Best-effort idea_id: query param first (e.g. /api/script/generate),
    then path param (e.g. /api/catalog/{idea_id}/lock)."""
    query_idea_id = request.query_params.get("idea_id")
    if query_idea_id:
        return query_idea_id
    path_params = request.scope.get("path_params") or {}
    return path_params.get("idea_id")


def _resolve_session_token(request: Request) -> str | None:
    authorization = request.headers.get("authorization")
    if not authorization:
        return None
    try:
        user_id = supabase_auth.get_user_id(authorization)
        return guard.get_or_create_user_session(user_id)
    except Exception:  # noqa: BLE001 — audit trail must never break the endpoint
        # Auth failures are the endpoint's job to report (401); the audit
        # trail simply has nothing to attribute the request to.
        return None


def _status_for(response_status: int) -> str:
    if response_status == 202:
        return "queued"
    if 200 <= response_status < 300:
        return "done"
    return "failed"


def _read_job_info(body: bytes) -> tuple[str | None, int | None]:
    """(job id, charged credits) from a JSON response body; (None, None) if absent.

    Credits are only reported for a job this request actually created and
    priced (`created` is not False and job.credits is a positive int).
    """
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    job = data.get("job")
    if not isinstance(job, dict):
        return None, None
    raw_id = job.get("id")
    job_id = str(raw_id) if raw_id else None
    credits = job.get("credits")
    if (
        not job_id
        or data.get("created") is False
        or isinstance(credits, bool)
        or not isinstance(credits, int)
        or credits <= 0
    ):
        credits = None
    return job_id, credits


class AgentActionsAuditMiddleware(BaseHTTPMiddleware):
    """Writes an agent_actions row for every audited pipeline request."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        should_audit = request.method in _AUDITED_METHODS and _is_audited_path(path)

        action_header = request.headers.get("x-agent-action-id") if should_audit else None

        response = await call_next(request)

        job_id: str | None = None
        credits: int | None = None
        if should_audit and 200 <= response.status_code < 300:
            try:
                response, body = await self._peek_json_body(response)
                if body is not None:
                    job_id, credits = _read_job_info(body)
            except Exception:
                logger.exception("[agent_actions] could not read the response body")

        if should_audit:
            try:
                self._record(request, response, action_header, path, job_id, credits)
            except Exception:
                logger.exception("[agent_actions] audit trail write failed")

        return response

    @staticmethod
    async def _peek_json_body(response: Response) -> tuple[Response, bytes | None]:
        """Read a small JSON body without changing what the client receives.

        Returns the response to send (rebuilt from the buffered chunks when the
        body iterator had to be consumed) and the body bytes, or None when the
        response is not a small JSON body (then it is returned untouched).
        """
        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response, None
        declared = response.headers.get("content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > _MAX_BODY_BYTES):
            return response, None
        iterator = getattr(response, "body_iterator", None)
        if iterator is None:
            body = getattr(response, "body", None)
            return response, body if isinstance(body, bytes) else None

        chunks: list[bytes] = []
        try:
            async for chunk in iterator:
                chunks.append(chunk if isinstance(chunk, bytes) else str(chunk).encode("utf-8"))
        finally:
            body = b"".join(chunks)
            rebuilt = Response(
                content=body,
                status_code=response.status_code,
                background=getattr(response, "background", None),
            )
            # Keep every original header (incl. repeated Set-Cookie) as-is.
            rebuilt.raw_headers = list(response.raw_headers)
        return rebuilt, body

    def _record(
        self,
        request: Request,
        response: Response,
        action_header: str | None,
        path: str,
        job_id: str | None = None,
        credits: int | None = None,
    ) -> None:
        session_token = _resolve_session_token(request)
        if session_token is None:
            return

        status_value = _status_for(response.status_code)
        error = None if status_value != "failed" else f"HTTP {response.status_code}"
        extra: dict[str, object] = {}
        if job_id:
            extra["result_ref"] = job_id
        if credits is not None:
            extra["credits"] = credits

        if action_header:
            updated = update_action(
                action_header,
                session_token,
                {"status": status_value, "error": error, **extra},
            )
            if updated is not None:
                return
            # The header didn't match a pending row this session owns --
            # fall through and record the request as a button action so it
            # isn't dropped from the trail.

        create_action(
            session_token=session_token,
            step=_step_for_path(path),
            source="button",
            action=f"{request.method} {_route_template(request)}",
            idea_id=_extract_idea_id(request),
            credits=credits,
            status=status_value,
            error=error,
            result_ref=job_id,
        )
