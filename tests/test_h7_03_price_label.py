"""Tests for PIECE H7-03 — the price on the Render button is the price charged.

The GET state and POST /render both read the engine version through
`get_engine_version()`; /health is mocked here (no network) with a cold cache.
"""
from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.editing import dispatch as dispatch_mod
from app.editing import router as router_mod
from app.editing.store import get_or_create_edit, save_edit
from tests.test_editing_e2_05_pricing import (
    HEADERS,
    _prepare_raw_ready,
    _setup_env,  # noqa: F401  (autouse fixture: storage reset + mocked auth/credits)
    client,
)

PREV_ENGINE = "2026.09.27-1"
NEW_ENGINE = "2026.09.29-1"


class _FakeHealthClient:
    """Stands in for httpx.AsyncClient; `outcome` is a version str or an exception."""

    outcome: Any = NEW_ENGINE
    timeouts: list[float] = []

    def __init__(self, timeout: float = 5.0, **_: Any) -> None:
        type(self).timeouts.append(timeout)

    async def __aenter__(self) -> _FakeHealthClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def get(self, url: str) -> httpx.Response:
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return httpx.Response(
            200, json={"engine_version": self.outcome}, request=httpx.Request("GET", url)
        )


@pytest.fixture
def health(monkeypatch: pytest.MonkeyPatch) -> type[_FakeHealthClient]:
    """Cold engine cache and the REAL get_engine_version reading a fake /health."""
    monkeypatch.setattr(router_mod, "get_engine_version", dispatch_mod.get_engine_version)
    monkeypatch.setattr(dispatch_mod.httpx, "AsyncClient", _FakeHealthClient)
    _FakeHealthClient.outcome = NEW_ENGINE
    _FakeHealthClient.timeouts = []
    dispatch_mod._reset_engine_version_cache()
    return _FakeHealthClient


def _seed_done_render() -> None:
    """A done render of the current content, recorded with PREV_ENGINE."""
    _prepare_raw_ready()
    state = client.get("/api/editing/idea1", headers=HEADERS).json()
    content_hash = router_mod._render_content_hash(state["ir"], "renders/raw.mp4")
    edit = get_or_create_edit("tok_test", "idea1")
    save_edit(
        "tok_test",
        "idea1",
        {
            "render": {
                "status": "done",
                "storage_path": "renders/v1.mp4",
                "content_hash": content_hash,
                "engine_version": PREV_ENGINE,
            }
        },
        expected_version=edit["version"],
    )
    dispatch_mod._reset_engine_version_cache()


def _label_and_charge() -> tuple[dict[str, Any], dict[str, Any]]:
    state = client.get("/api/editing/idea1", headers=HEADERS).json()
    resp = client.post("/api/editing/idea1/render", headers=HEADERS)
    assert resp.status_code == 202
    return state, resp.json()["job"]


def test_cold_cache_engine_changed_label_and_charge_are_free(health) -> None:
    _seed_done_render()
    health.outcome = NEW_ENGINE

    state, job = _label_and_charge()

    assert state["render_price"] == 0
    assert state["render_price_kind"] == "engine_updated"
    assert state["engine_version"] == NEW_ENGINE
    assert state["last_render_engine_version"] == PREV_ENGINE
    assert job["credits"] == 0


def test_cold_cache_same_engine_label_and_charge_are_5(health) -> None:
    _seed_done_render()
    health.outcome = PREV_ENGINE

    state, job = _label_and_charge()

    assert state["render_price"] == 5
    assert state["render_price_kind"] == "again"
    assert job["credits"] == 5


def test_no_previous_render_label_and_charge_are_20(health) -> None:
    _prepare_raw_ready()
    health.outcome = NEW_ENGINE

    state, job = _label_and_charge()

    assert state["render_price"] == 20
    assert state["render_price_kind"] == "first"
    assert state["last_render_engine_version"] is None
    assert job["credits"] == 20


def test_health_timeout_on_get_labels_5_and_never_free(health) -> None:
    _seed_done_render()
    health.outcome = httpx.ReadTimeout("slow /health")
    health.timeouts = []

    state = client.get("/api/editing/idea1", headers=HEADERS).json()

    assert state["render_price"] == 5
    assert state["render_price_kind"] == "again"
    assert state["engine_version"] == "unknown"
    assert health.timeouts == [2.0]


def test_health_timeout_on_get_then_live_read_says_engine_changed(health) -> None:
    """Label 5 while /health is down; when the charge's live read works it is 0 or 5, never label 0 / charge 5."""
    _seed_done_render()
    health.outcome = httpx.ReadTimeout("slow /health")
    state = client.get("/api/editing/idea1", headers=HEADERS).json()
    assert state["render_price"] == 5

    health.outcome = NEW_ENGINE
    resp = client.post("/api/editing/idea1/render", headers=HEADERS)
    assert resp.status_code == 202
    assert resp.json()["job"]["credits"] in (0, 5)


def test_health_timeout_on_both_reads_charges_5(health) -> None:
    _seed_done_render()
    health.outcome = httpx.ReadTimeout("slow /health")

    state, job = _label_and_charge()

    assert state["render_price"] == 5
    assert job["credits"] == 5


def test_get_engine_version_default_timeout_is_2s(health) -> None:
    import asyncio

    asyncio.run(dispatch_mod.get_engine_version())
    asyncio.run(_reset_and_read(4.0))
    assert health.timeouts == [2.0, 4.0]


async def _reset_and_read(timeout_s: float) -> None:
    dispatch_mod._reset_engine_version_cache()
    await dispatch_mod.get_engine_version(timeout_s=timeout_s)
