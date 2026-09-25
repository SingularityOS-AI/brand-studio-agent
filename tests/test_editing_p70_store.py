"""Tests for editing store, config, and migration 012 (Pieza 70 — Bloque E)."""
from pathlib import Path
import pytest

from app.editing import config, store


@pytest.fixture(autouse=True)
def setup_local_store(monkeypatch):
    """Force local in-memory mode and reset state before and after each test."""
    monkeypatch.setattr(store, "_get_edits_client", lambda: None)
    store._reset_local_edits()
    yield
    store._reset_local_edits()


def test_get_edit_and_get_or_create():
    """1. get_edit of non-existent record returns None; get_or_create_edit creates version==1 with 7 empty dict fields."""
    assert store.get_edit("tok1", "idea1") is None

    edit1 = store.get_or_create_edit("tok1", "idea1")
    assert edit1["session_token"] == "tok1"
    assert edit1["idea_id"] == "idea1"
    assert edit1["version"] == 1
    assert "id" in edit1

    for field in config.EDIT_FIELDS:
        assert edit1[field] == {}

    edit2 = store.get_or_create_edit("tok1", "idea1")
    assert edit1["id"] == edit2["id"]
    assert store.get_edit("tok1", "idea1")["id"] == edit1["id"]


def test_save_edit_success():
    """2. save_edit updates field, increments version to expected_version + 1, leaves other fields intact."""
    store.get_or_create_edit("tok1", "idea1")

    updated = store.save_edit("tok1", "idea1", {"timeline": {"a": 1}}, expected_version=1)
    assert updated["version"] == 2
    assert updated["timeline"] == {"a": 1}

    for field in config.EDIT_FIELDS:
        if field != "timeline":
            assert updated[field] == {}


def test_save_edit_version_conflict():
    """3. save_edit with stale expected_version raises EditVersionConflict with correct expected and current."""
    store.get_or_create_edit("tok1", "idea1")
    store.save_edit("tok1", "idea1", {"timeline": {"a": 1}}, expected_version=1)  # now version is 2

    with pytest.raises(store.EditVersionConflict) as exc_info:
        store.save_edit("tok1", "idea1", {"timeline": {"b": 2}}, expected_version=1)

    assert exc_info.value.expected == 1
    assert exc_info.value.current == 2


def test_save_edit_invalid_fields_and_values():
    """4. Unknown field name or non-dict value raises ValueError."""
    store.get_or_create_edit("tok1", "idea1")

    with pytest.raises(ValueError):
        store.save_edit("tok1", "idea1", {"invalid_field": {}}, expected_version=1)

    with pytest.raises(ValueError):
        store.save_edit("tok1", "idea1", {"timeline": "not_a_dict"}, expected_version=1)


def test_session_token_isolation():
    """5. Two session_tokens with the same idea_id do not share data."""
    e1 = store.get_or_create_edit("token_a", "shared_idea")
    e2 = store.get_or_create_edit("token_b", "shared_idea")

    assert e1["id"] != e2["id"]

    store.save_edit("token_a", "shared_idea", {"timeline": {"x": 10}}, expected_version=1)
    e2_check = store.get_edit("token_b", "shared_idea")
    assert e2_check["timeline"] == {}
    assert e2_check["version"] == 1


def test_returned_dict_immutability():
    """6. Mutating the returned dict does not alter internal stored state."""
    e = store.get_or_create_edit("tok1", "idea1")
    e["timeline"]["mutated"] = True

    e_fetched = store.get_edit("tok1", "idea1")
    assert e_fetched["timeline"] == {}

    saved = store.save_edit("tok1", "idea1", {"dressing": {"d": 1}}, expected_version=1)
    saved["dressing"]["d"] = 999

    e_fetched2 = store.get_edit("tok1", "idea1")
    assert e_fetched2["dressing"] == {"d": 1}


def test_migration_012_sql_content():
    """7. Migration 012 SQL file contains required tables, constraints, and functions."""
    migration_path = Path(__file__).parent.parent / "supabase" / "migrations" / "012_editing.sql"
    sql_text = migration_path.read_text(encoding="utf-8")

    assert "asset_jobs_kind_check" in sql_text

    required_kinds = [
        "'a_roll_take'",
        "'transcript'",
        "'stock'",
        "'ai_image'",
        "'ai_video'",
        "'motion_graphic'",
        "'music'",
        "'sfx'",
        "'raw_render'",
        "'render'",
        "'redress'",
    ]
    for k in required_kinds:
        assert k in sql_text, f"Missing kind {k} in migration 012"

    assert "create table if not exists edits" in sql_text
    assert "unique (session_token, idea_id)" in sql_text
    assert "enable row level security" in sql_text
    assert "create or replace function refund_credits" in sql_text
    assert "set search_path" in sql_text
    # refund mints credits: only the backend (service_role) may execute it
    assert "revoke execute on function refund_credits(text, integer) from public, anon, authenticated" in sql_text


def test_config_values():
    """8. Config constants match spec defaults."""
    assert config.RENDER_CREDITS == 20
    assert config.REDRESS_CREDITS == 2
    assert config.GAP_MS == 400
    assert config.PAD_MS == 100
    assert len(config.EDIT_FIELDS) == 7
