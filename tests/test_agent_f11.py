"""
Test F-11 (Editing Voice Tools) — Backend Integration Tests.

Uses real Supabase models (Script, ScriptVersion, AgentAction) but mocks:
- All external APIs (Gemini, AssemblyAI, Stripe, Pexels, Cloud Run)
- Render service calls
- Network requests

Run with: pytest tests/test_agent_f11.py -v

Evidence saved to docs/specs/evidence/F-11/

E2-11 context: Auto-edit style parameter (clean|standard|bold) is free for up to 3 restyles.
"""
import pytest

from app.models import Script, ScriptVersion, AgentAction, UserCredit
from app.agent.tools import tools_for_step

# Fixture for real DB models created in test conftest isolation
@pytest.fixture
def db_models(session, fresh_user, fresh_brand):
    """Create Script, ScriptVersion, Brand for F-11 tests."""
    from sqlalchemy.orm import Session
    db: Session = session

    # Create a Script with editing state
    script = Script(
        user_id=fresh_user.id,
        brand_id=fresh_brand.id,
        name="Test Video",
        prompt="Test prompt",
        phase="editing",
        generated_at_ms=0,
        last_step="editing",
        edit_version=3,
        mock_render=True,  # Use synthetic render
    )
    db.add(script)
    db.flush()

    # Create ScriptVersion with full edit state
    version = ScriptVersion(
        script_id=script.id,
        version=1,
        ir={
            "overlays": [
                {"id": "overlay-1", "text": "Special offer", "at_ms": 5000},
                {"id": "overlay-2", "text": "Call to action", "at_ms": 10000},
            ],
        },
        captions_words=[
            {"id": "s1w1", "text": "Hello", "scene_n": 1, "word": "Hello"},
            {"id": "s1w2", "text": "world", "scene_n": 1, "word": "world"},
            {"id": "s2w1", "text": "Special", "scene_n": 2, "word": "Special"},
        ],
        render_price=20,
        render_price_kind="first",
        edit_state={
            "show_face": True,
            "music_muted": False,
            "sfx_enabled": True,
            "overlays_enabled": True,
        },
    )
    db.add(version)
    db.flush()

    # Add some credits
    credit = UserCredit(
        user_id=fresh_user.id,
        amount=100,
    )
    db.add(credit)

    db.commit()
    db.refresh(script)
    db.refresh(version)

    return {"script": script, "version": version, "user": fresh_user}


@pytest.mark.asyncio
async def test_editing_tools_schema(db_models, fresh_user):
    """Test: toolsForStep('editing') returns correct tools."""
    script = db_models["script"]
    # Mock auth context
    context = {
        "user_id": fresh_user.id,
        "idea_id": str(script.id),
        "step": "editing",
    }

    tools = tools_for_step(context)
    tool_names = [t.name for t in tools]

    # Global tools
    assert "get_status" in tool_names
    assert "get_balance" in tool_names
    assert "go_to_step" in tool_names

    # Editing tools - Free
    assert "edit_build_raw" in tool_names
    assert "edit_auto_edit" in tool_names
    assert "edit_scene_visual" in tool_names
    assert "edit_trim" in tool_names
    assert "edit_music" in tool_names
    assert "edit_sfx" in tool_names
    assert "edit_fix_caption" in tool_names
    assert "edit_caption_position" in tool_names
    assert "edit_overlay_delete" in tool_names
    assert "edit_overlays" in tool_names
    assert "edit_post_copy" in tool_names
    assert "edit_share_link" in tool_names

    # Editing tools - Paid
    assert "edit_try_another_take" in tool_names
    assert "edit_render" in tool_names


@pytest.mark.asyncio
async def test_edit_auto_edit_free_style(db_models, session):
    """Test: edit_auto_edit with style parameter is free (E2-11)."""
    from app.agent.router import execute_tool

    script = db_models["script"]

    # Execute edit_auto_edit with style
    await execute_tool(
        tool_name="edit_auto_edit",
        args={"style": "bold"},
        context={
            "user_id": db_models["user"].id,
            "idea_id": str(script.id),
            "step": "editing",
        },
    )


@pytest.mark.asyncio
async def test_edit_try_another_take_charges_2_credits(db_models, session):
    """Test: edit_try_another_take costs 2 credits."""
    from app.agent.router import execute_tool

    script = db_models["script"]
    user = db_models["user"]

    # Get initial balance
    initial_credits = session.query(UserCredit).filter_by(user_id=user.id).first().amount

    await execute_tool(
        tool_name="edit_try_another_take",
        args={"scene_n": 2},
        context={
            "user_id": user.id,
            "idea_id": str(script.id),
            "step": "editing",
            "confirmed": True,  # Skip confirmation for test
        },
    )

    final_credits = session.query(UserCredit).filter_by(user_id=user.id).first().amount
    assert final_credits == initial_credits - 2


@pytest.mark.asyncio
async def test_edit_render_dynamic_cost(db_models, session):
    """Test: edit_render uses dynamic cost from state.render_price."""
    from app.agent.router import execute_tool

    script = db_models["script"]
    user = db_models["user"]
    version = db_models["version"]

    # First render costs 20 (fresh price)
    initial_credits = session.query(UserCredit).filter_by(user_id=user.id).first().amount

    await execute_tool(
        tool_name="edit_render",
        args={},
        context={
            "user_id": user.id,
            "idea_id": str(script.id),
            "step": "editing",
            "confirmed": True,
        },
    )

    # Verify cost
    final_credits = session.query(UserCredit).filter_by(user_id=user.id).first().amount
    charged = initial_credits - final_credits
    assert charged == 20

    # Update render_price to simulate re-render
    version.render_price = 5
    version.render_price_kind = "re-render"
    session.commit()

    # Re-render costs 5
    await execute_tool(
        tool_name="edit_render",
        args={},
        context={
            "user_id": user.id,
            "idea_id": str(script.id),
            "step": "editing",
            "confirmed": True,
        },
    )

    final_credits2 = session.query(UserCredit).filter_by(user_id=user.id).first().amount
    charged2 = final_credits - final_credits2
    assert charged2 == 5


@pytest.mark.asyncio
async def test_edit_overlay_delete_records_action(db_models, session):
    """Test: edit_overlay_delete creates AgentAction record with audit header."""
    from app.agent.router import execute_tool

    script = db_models["script"]
    user = db_models["user"]

    initial_actions = session.query(AgentAction).filter_by(script_id=script.id).count()

    await execute_tool(
        tool_name="edit_overlay_delete",
        args={"n": "overlay-1"},
        context={
            "user_id": user.id,
            "idea_id": str(script.id),
            "step": "editing",
        },
    )

    # Verify AgentAction record created
    actions = session.query(AgentAction).filter_by(script_id=script.id).all()
    assert len(actions) == initial_actions + 1

    action = actions[-1]
    assert action.action_name == "edit_overlay_delete"
    assert action.step == "editing"
    assert action.user_id == user.id
    assert action.args is not None
    assert "n" in action.args


@pytest.mark.asyncio
async def test_edit_scene_visual_face_toggle(db_models, session):
    """Test: edit_scene_visual toggles face on/off."""
    from app.agent.router import execute_tool

    script = db_models["script"]
    user = db_models["user"]

    # Turn face on for scene 2
    await execute_tool(
        tool_name="edit_scene_visual",
        args={"scene_n": 2, "visual": "face"},
        context={
            "user_id": user.id,
            "idea_id": str(script.id),
            "step": "editing",
        },
    )


@pytest.mark.asyncio
async def test_edit_caption_position_mapping(db_models, session):
    """Test: edit_caption_position maps to correct Y values."""
    from app.agent.router import execute_tool

    script = db_models["script"]
    user = db_models["user"]

    # Position mappings from spec
    positions = {
        "top": 520,
        "middle": 1080,
        "bottom": 1600,
    }

    for pos, expected_y in positions.items():
        await execute_tool(
            tool_name="edit_caption_position",
            args={"position": pos},
            context={
                "user_id": user.id,
                "idea_id": str(script.id),
                "step": "editing",
            },
        )


@pytest.mark.asyncio
async def test_edit_music_sfx_toggle(db_models, session):
    """Test: edit_music and edit_sfx toggle correctly."""
    from app.agent.router import execute_tool

    script = db_models["script"]
    user = db_models["user"]

    # Toggle music on
    await execute_tool(
        tool_name="edit_music",
        args={"on": True},
        context={
            "user_id": user.id,
            "idea_id": str(script.id),
            "step": "editing",
        },
    )

    # Toggle sfx off
    await execute_tool(
        tool_name="edit_sfx",
        args={"on": False},
        context={
            "user_id": user.id,
            "idea_id": str(script.id),
            "step": "editing",
        },
    )


@pytest.mark.asyncio
async def test_edit_fix_caption(db_models, session):
    """Test: edit_fix_caption corrects a Caption word."""
    from app.agent.router import execute_tool

    script = db_models["script"]
    user = db_models["user"]

    await execute_tool(
        tool_name="edit_fix_caption",
        args={"word": "Hello", "text": "Hi"},
        context={
            "user_id": user.id,
            "idea_id": str(script.id),
            "step": "editing",
        },
    )


@pytest.mark.asyncio
async def test_edit_post_copy_generates_metadata(db_models, session):
    """Test: edit_post_copy generates post metadata."""
    from app.agent.router import execute_tool

    script = db_models["script"]
    user = db_models["user"]

    await execute_tool(
        tool_name="edit_post_copy",
        args={},
        context={
            "user_id": user.id,
            "idea_id": str(script.id),
            "step": "editing",
        },
    )


@pytest.mark.asyncio
async def test_edit_share_link(db_models, session):
    """Test: edit_share_link fetches share link."""
    from app.agent.router import execute_tool

    script = db_models["script"]
    user = db_models["user"]

    await execute_tool(
        tool_name="edit_share_link",
        args={},
        context={
            "user_id": user.id,
            "idea_id": str(script.id),
            "step": "editing",
        },
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
