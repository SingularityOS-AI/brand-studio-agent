import logging
import asyncio

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.agent import store

logger = logging.getLogger(__name__)

class AgentAuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # We only care about POST/PATCH/DELETE
        if request.method not in ["POST", "PATCH", "DELETE"]:
            return await call_next(request)

        path = request.url.path

        # Paths to intercept
        if not path.startswith(("/api/catalog", "/api/script", "/api/audiovisual", "/api/editing", "/api/soul/generate")):
            return await call_next(request)

        # Exclude internal
        if path.startswith("/api/editing/internal"):
            return await call_next(request)

        action_id = request.headers.get("X-Agent-Action-Id")

        # Execute request
        try:
            response = await call_next(request)
        except Exception as e:
            # If exception, we still try to log if needed
            if action_id:
                try:
                    await store.update_action_async(action_id, {"status": "failed", "error": str(e)})
                except Exception as store_e:  # noqa: BLE001
                    logger.error(f"Failed to update action {action_id}: {store_e}")
            raise

        # Determine status from response
        status_code = response.status_code
        if status_code == 202:
            status_text = "queued"
        elif 200 <= status_code < 300:
            status_text = "done"
        else:
            status_text = "failed"

        try:
            if action_id:
                # Update voice action without blocking main thread
                asyncio.create_task(store.update_action_async(action_id, {"status": status_text}))
            else:
                # Insert button action
                route = request.scope.get("route")
                if route and hasattr(route, "path"):
                    action_name = f"{request.method} {route.path}"
                else:
                    action_name = f"{request.method} {path}"

                auth = request.headers.get("authorization")
                session_token = None
                if auth:
                    from app.auth import supabase_auth
                    from app.guard import guard
                    try:
                        user_id = supabase_auth.get_user_id(auth)
                        session_token = guard.get_or_create_user_session(user_id)
                    except Exception:  # noqa: BLE001, S110
                        pass

                if session_token:
                    # Fire and forget without blocking
                    asyncio.create_task(store.create_action_async({
                        "session_token": session_token,
                        "source": "button",
                        "action": action_name,
                        "status": status_text
                    }))
        except Exception as store_e:  # noqa: BLE001
            logger.error(f"AgentAuditMiddleware store error: {store_e}")

        return response
