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


class AgentActionsAuditMiddleware(BaseHTTPMiddleware):
    """Writes an agent_actions row for every audited pipeline request."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        path = request.url.path
        should_audit = request.method in _AUDITED_METHODS and _is_audited_path(path)

        action_header = request.headers.get("x-agent-action-id") if should_audit else None

        response = await call_next(request)

        if should_audit:
            try:
                self._record(request, response, action_header, path)
            except Exception:
                logger.exception("[agent_actions] audit trail write failed")

        return response

    def _record(
        self,
        request: Request,
        response: Response,
        action_header: str | None,
        path: str,
    ) -> None:
        session_token = _resolve_session_token(request)
        if session_token is None:
            return

        status_value = _status_for(response.status_code)
        error = None if status_value != "failed" else f"HTTP {response.status_code}"

        if action_header:
            updated = update_action(
                action_header,
                session_token,
                {"status": status_value, "error": error},
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
            status=status_value,
            error=error,
        )
