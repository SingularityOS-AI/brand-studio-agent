from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

from app.agent import store
from app.auth import supabase_auth
from app.guard import guard

agent_router = APIRouter()

def get_session_token(authorization: Optional[str] = Header(None)) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header"
        )
    user_id = supabase_auth.get_user_id(authorization)
    return guard.get_or_create_user_session(user_id)

class CreateActionRequest(BaseModel):
    utterance: Optional[str] = None
    restatement: Optional[str] = None
    action: str
    args: Optional[Dict[str, Any]] = None
    step: Optional[str] = None
    idea_id: Optional[str] = None
    credits: Optional[int] = None

class UpdateActionRequest(BaseModel):
    confirmation: Optional[str] = None
    confirmed_at: Optional[str] = None
    status: str

@agent_router.post("/actions")
async def create_agent_action(req: CreateActionRequest, session_token: str = Depends(get_session_token)):
    data = req.dict(exclude_none=True)
    data["session_token"] = session_token
    data["source"] = "voice"
    # proposed or queued depending on logic? Spec says: "creates a proposed/queued voice action"
    # I'll default to queued unless otherwise
    data["status"] = "proposed" if req.restatement else "queued"

    action = store.create_action(data)
    if "id" not in action:
        raise HTTPException(status_code=500, detail="Failed to create action")

    return {"id": action["id"]}

@agent_router.patch("/actions/{action_id}")
async def update_agent_action(action_id: str, req: UpdateActionRequest, session_token: str = Depends(get_session_token)):
    data = req.dict(exclude_none=True)
    updated = store.update_action(action_id, data, session_token=session_token)
    if not updated:
        raise HTTPException(status_code=404, detail="Action not found or unauthorized")
    return updated

@agent_router.get("/actions")
async def list_agent_actions(idea_id: Optional[str] = None, limit: int = 50, session_token: str = Depends(get_session_token)):
    return store.list_actions(session_token, idea_id, limit)
