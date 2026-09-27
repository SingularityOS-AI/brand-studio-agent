"""Tests for Piece E2-03 — Empty-scene guard + English warning.

Covers:
- the luma std-dev empty-scene decision function (pure, no ffmpeg needed)
- render_service.ffmpeg_raw sampling a real near-blank motion-graphic scene and
  build_raw() swapping it for the founder's face take, or the scene's AI image
  when the manifest declares one (skipped when ffmpeg is not on PATH)
- app/editing/dispatch.py forwarding scene_fallbacks from the render service
- app/editing/router.py exposing scene_fallbacks + the English warning text
- the warning banner wiring in app/static/editing.js
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.audiovisual.jobs import _reset_local_jobs, create_job
from app.auth.supabase_auth import supabase_auth
from app.editing import config as dispatch_config
from app.editing.dispatch import call_render_service, resolve_raw_render
from app.editing.router import router
from app.editing.store import _reset_local_edits, get_edit, save_edit
from render_service.ffmpeg_raw import (
    _is_empty_motion_graphic,
    _sample_luma_stddevs,
    build_raw,
)
from render_service.manifest import (
    Broll,
    Canvas,
    InputRef,
    RenderRequest,
    Segment,
    Timeline,
    TimelineScene,
    TimelineSettings,
    Trim,
    timeline_hash,
)
from render_service.motion import chromium_path, convert_html

REPO_ROOT = Path(__file__).resolve().parent.parent
EDITING_JS = REPO_ROOT / "app" / "static" / "editing.js"

FFMPEG_MISSING = shutil.which("ffmpeg") is None

app = FastAPI()
app.include_router(router)
client = TestClient(app)
HEADERS = {"authorization": "Bearer tok_test"}


# ---------------------------------------------------------------------------
# 1. Pure decision function: _is_empty_motion_graphic (no ffmpeg required)
# ---------------------------------------------------------------------------


def test_is_empty_true_when_over_90pct_samples_near_uniform():
    stddevs = [1.0] * 37 + [10.0] * 3  # 37/40 = 92.5% below threshold
    assert _is_empty_motion_graphic(stddevs) is True


def test_is_empty_false_when_exactly_90pct_samples_near_uniform():
    stddevs = [1.0] * 9 + [10.0] * 1  # exactly 90% -> spec requires ">90%"
    assert _is_empty_motion_graphic(stddevs) is False


def test_is_empty_false_for_normal_video_stddevs():
    stddevs = [12.0, 15.0, 9.5, 20.0, 30.0]
    assert _is_empty_motion_graphic(stddevs) is False


def test_is_empty_false_when_no_samples():
    """A sampling failure (e.g. ffmpeg missing) must never trigger a fallback."""
    assert _is_empty_motion_graphic([]) is False


# ---------------------------------------------------------------------------
# 2. Real ffmpeg sampling: near-black vs. normal video
# ---------------------------------------------------------------------------


def _make_uniform_video(path: Path, duration_s: float = 2.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c=0x101010:s=320x240:d={duration_s}",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            str(path),
        ],
        check=True, capture_output=True,
    )


def _make_normal_video(path: Path, duration_s: float = 2.0, w: int = 320, h: int = 240) -> None:
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc2=s={w}x{h}:d={duration_s}:r=30",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            str(path),
        ],
        check=True, capture_output=True,
    )


@pytest.mark.render
@pytest.mark.skipif(FFMPEG_MISSING, reason="ffmpeg not installed")
def test_sample_luma_stddevs_flags_near_black_video_as_empty(tmp_path):
    video = tmp_path / "blank.mp4"
    _make_uniform_video(video)
    stddevs = _sample_luma_stddevs(video)
    assert stddevs, "expected at least one sampled frame"
    assert _is_empty_motion_graphic(stddevs) is True


@pytest.mark.render
@pytest.mark.skipif(FFMPEG_MISSING, reason="ffmpeg not installed")
def test_sample_luma_stddevs_does_not_flag_normal_video(tmp_path):
    video = tmp_path / "normal.mp4"
    _make_normal_video(video)
    stddevs = _sample_luma_stddevs(video)
    assert stddevs, "expected at least one sampled frame"
    assert _is_empty_motion_graphic(stddevs) is False


# ---------------------------------------------------------------------------
# 3. build_raw(): a deliberately blank MG scene never ships blank
# ---------------------------------------------------------------------------


def _make_face_video(path: Path, duration_s: float = 4.0) -> None:
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"testsrc2=s=1080x1920:d={duration_s}:r=30",
            "-f", "lavfi", "-i", f"sine=f=440:d={duration_s}",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            str(path),
        ],
        check=True, capture_output=True,
    )


def _make_fallback_timeline(scene2_broll: Broll | None) -> Timeline:
    """1 face scene (0-2s) + 1 broll scene (2-4s) carrying scene2_broll."""
    return Timeline(
        schema="brandstudio.timeline.v1",
        edit_version=1,
        canvas=Canvas(w=1080, h=1920, fps=30),
        settings=TimelineSettings(
            gap_ms=400, pad_ms=100, music_volume=0.2, music_muted=True, sfx_enabled=False
        ),
        scenes=[
            TimelineScene(
                n=1,
                phase="hook",
                visual="face",
                take_job_id="take_job_1",
                take_input="take_1",
                broll=None,
                segments=[Segment(in_ms=0, out_ms=2000, out_start_ms=0)],
                trim=Trim(start_ms=0, end_ms=0),
                out_start_ms=0,
                out_end_ms=2000,
            ),
            TimelineScene(
                n=2,
                phase="body",
                visual="broll",
                take_job_id="take_job_1",
                take_input="take_1",
                broll=scene2_broll,
                segments=[Segment(in_ms=0, out_ms=2000, out_start_ms=2000)],
                trim=Trim(start_ms=0, end_ms=0),
                out_start_ms=2000,
                out_end_ms=4000,
            ),
        ],
        music=None,
        duration_ms=4000,
        hash="sample_hash_e2_03",
    )


def _make_request(timeline: Timeline, extra_inputs: dict[str, InputRef]) -> RenderRequest:
    inputs = {
        "take_1": InputRef(url="https://example.com/take1.mp4", kind="video"),
        "broll_s2": InputRef(url="https://example.com/mg.mp4", kind="html"),
        **extra_inputs,
    }
    return RenderRequest.model_validate(
        {
            "schema": "brandstudio.render.v1",
            "job_id": "job_e2_03",
            "attempt": 1,
            "mode": "raw",
            "timeline": timeline.model_dump(),
            "inputs": {k: v.model_dump() for k, v in inputs.items()},
            "convert": [],
            "output": {
                "upload_url": "https://example.com/upload",
                "storage_path": "output/video.mp4",
                "max_bytes": 47000000,
            },
            "progress_url": None,
        }
    )


@pytest.mark.render
@pytest.mark.skipif(FFMPEG_MISSING, reason="ffmpeg not installed")
def test_build_raw_falls_back_to_face_when_motion_graphic_is_empty(tmp_path):
    take_path = tmp_path / "take_1.mp4"
    mg_path = tmp_path / "mg_broll.mp4"
    _make_face_video(take_path, duration_s=4.0)
    _make_uniform_video(mg_path, duration_s=2.0)

    broll = Broll(kind="motion_graphic", input_id="broll_s2")
    timeline = _make_fallback_timeline(broll)
    request = _make_request(timeline, {})

    local_inputs = {"take_1": take_path, "broll_s2": mg_path}
    workdir = tmp_path / "work"

    result = build_raw(request, local_inputs, workdir)

    assert result["scene_fallbacks"] == [
        {"scene_n": 2, "used": "face", "reason": "empty_motion_graphic"}
    ]
    out_path = Path(result["path"])
    assert out_path.exists() and out_path.stat().st_size > 0

    # Scene 2 (2s-4s of the 4s output) must now show the face take's texture,
    # not the blank motion graphic it replaced.
    stddevs = _sample_luma_stddevs(out_path)  # sample_hz defaults to 4 -> 4/s
    scene2_stddevs = stddevs[8:]
    assert scene2_stddevs
    assert _is_empty_motion_graphic(scene2_stddevs) is False


@pytest.mark.render
@pytest.mark.skipif(FFMPEG_MISSING, reason="ffmpeg not installed")
def test_build_raw_falls_back_to_ai_image_when_manifest_declares_one(tmp_path):
    take_path = tmp_path / "take_1.mp4"
    mg_path = tmp_path / "mg_broll.mp4"
    image_path = tmp_path / "fallback.png"
    _make_face_video(take_path, duration_s=4.0)
    _make_uniform_video(mg_path, duration_s=2.0)
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=green:s=640x360",
            "-frames:v", "1", str(image_path),
        ],
        check=True, capture_output=True,
    )

    broll = Broll(kind="motion_graphic", input_id="broll_s2")
    timeline = _make_fallback_timeline(broll)
    request = _make_request(
        timeline, {"broll_s2_image": InputRef(url="https://example.com/fallback.png", kind="image")}
    )

    local_inputs = {
        "take_1": take_path,
        "broll_s2": mg_path,
        "broll_s2_image": image_path,
    }
    workdir = tmp_path / "work"

    result = build_raw(request, local_inputs, workdir)

    assert result["scene_fallbacks"] == [
        {"scene_n": 2, "used": "image", "reason": "empty_motion_graphic"}
    ]
    out_path = Path(result["path"])
    assert out_path.exists() and out_path.stat().st_size > 0


@pytest.mark.render
@pytest.mark.skipif(FFMPEG_MISSING, reason="ffmpeg not installed")
def test_build_raw_leaves_normal_motion_graphic_untouched(tmp_path):
    take_path = tmp_path / "take_1.mp4"
    mg_path = tmp_path / "mg_broll.mp4"
    _make_face_video(take_path, duration_s=4.0)
    _make_normal_video(mg_path, duration_s=2.0, w=1080, h=1920)

    broll = Broll(kind="motion_graphic", input_id="broll_s2")
    timeline = _make_fallback_timeline(broll)
    request = _make_request(timeline, {})

    local_inputs = {"take_1": take_path, "broll_s2": mg_path}
    workdir = tmp_path / "work"

    result = build_raw(request, local_inputs, workdir)

    assert result["scene_fallbacks"] == []
    assert Path(result["path"]).exists()


_BLANK_MG_HTML = """<!doctype html>
<html>
<head>
<style>
  html, body { margin:0; padding:0; background:#000000; width:1080px; height:1920px; overflow:hidden; }
  .ghost {
    position:absolute; top:800px; left:90px; width:900px; height:320px;
    color:#000000; background:#000000; font-size:64px; font-family:sans-serif;
  }
</style>
<script src="https://cdn.jsdelivr.net/npm/gsap@3.12.5/dist/gsap.min.js"></script>
</head>
<body>
  <div class="ghost" id="el">Same color as the background: never visible.</div>
  <script>
    const tl = gsap.timeline({ paused: true });
    tl.to("#el", { opacity: 1, duration: 3 });
    window.__timelines = { main: tl };
  </script>
</body>
</html>
"""


@pytest.mark.render
@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or chromium_path() is None,
    reason="ffmpeg and Chromium are required for this end-to-end test",
)
def test_build_raw_end_to_end_from_a_deliberately_blank_mg_html(tmp_path):
    """The literal 'Done when' scenario: a real motion-graphic HTML whose on-screen
    content is invisible (text color == background) goes through the real HTML->MP4
    converter, then through build_raw()'s guard, and the scene lands on the founder's
    face — never the blank motion graphic. Saves frame evidence for the PR."""
    html_path = tmp_path / "blank_mg.html"
    html_path.write_text(_BLANK_MG_HTML, encoding="utf-8")

    mg_out = tmp_path / "mg_converted.mp4"
    convert_html(html_path, mg_out, duration_s=2.0, workdir=tmp_path / "convert_work")
    assert mg_out.exists() and mg_out.stat().st_size > 0

    # Sanity check: the converter's own output is indeed near-uniform (the fixture
    # is doing what it says), so the guard below is the thing catching it.
    mg_stddevs = _sample_luma_stddevs(mg_out)
    assert mg_stddevs and _is_empty_motion_graphic(mg_stddevs) is True

    take_path = tmp_path / "take_1.mp4"
    _make_face_video(take_path, duration_s=4.0)

    broll = Broll(kind="motion_graphic", input_id="broll_s2")
    timeline = _make_fallback_timeline(broll)
    request = _make_request(timeline, {})

    local_inputs = {"take_1": take_path, "broll_s2": mg_out}
    workdir = tmp_path / "work"

    result = build_raw(request, local_inputs, workdir)

    assert result["scene_fallbacks"] == [
        {"scene_n": 2, "used": "face", "reason": "empty_motion_graphic"}
    ]
    out_path = Path(result["path"])
    assert out_path.exists() and out_path.stat().st_size > 0

    stddevs = _sample_luma_stddevs(out_path)
    scene2_stddevs = stddevs[8:]  # scene 2 starts at 2s, sample_hz defaults to 4/s
    assert scene2_stddevs
    assert _is_empty_motion_graphic(scene2_stddevs) is False

    evidence_dir = REPO_ROOT / "docs" / "specs" / "evidence" / "E2-03"
    evidence_dir.mkdir(parents=True, exist_ok=True)

    def _extract_frame(video: Path, t_s: float, out_png: Path) -> None:
        subprocess.run(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-ss", f"{t_s:.3f}", "-i", str(video),
                "-vframes", "1", "-q:v", "2", str(out_png),
            ],
            check=True, capture_output=True,
        )

    _extract_frame(mg_out, 1.0, evidence_dir / "blank_mg_source_frame.png")
    _extract_frame(out_path, 3.0, evidence_dir / "raw_cut_scene2_after_fallback_frame.png")

    (evidence_dir / "luma_stddev_measurement.txt").write_text(
        "blank_mg_source stddevs (sampled every 250ms): "
        f"{[round(s, 2) for s in mg_stddevs]}\n"
        "raw_cut scene 2 stddevs after the guard (sampled every 250ms): "
        f"{[round(s, 2) for s in scene2_stddevs]}\n"
        f"scene_fallbacks returned by build_raw(): {result['scene_fallbacks']}\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# 4. dispatch.py: scene_fallbacks forwarded from the render service response
# ---------------------------------------------------------------------------


def _make_valid_timeline_dict() -> dict:
    tl = {
        "schema": "brandstudio.timeline.v1",
        "edit_version": 1,
        "canvas": {"w": 1080, "h": 1920, "fps": 30},
        "settings": {
            "gap_ms": 400,
            "pad_ms": 100,
            "music_volume": 0.2,
            "music_muted": False,
            "sfx_enabled": True,
        },
        "scenes": [
            {
                "n": 1,
                "phase": "hook",
                "visual": "face",
                "take_job_id": "take_job_1",
                "take_input": "input_take_1",
                "broll": None,
                "segments": [{"in_ms": 0, "out_ms": 3000, "out_start_ms": 0}],
                "trim": {"start_ms": 0, "end_ms": 0},
                "out_start_ms": 0,
                "out_end_ms": 3000,
            },
            {
                "n": 2,
                "phase": "body_1",
                "visual": "broll",
                "take_job_id": "take_job_2",
                "take_input": "input_take_2",
                "broll": {
                    "kind": "motion_graphic",
                    "input_id": "input_mg_2",
                    "w": 1080,
                    "h": 1920,
                    "duration_ms": 2000,
                },
                "segments": [{"in_ms": 0, "out_ms": 2000, "out_start_ms": 3000}],
                "trim": {"start_ms": 0, "end_ms": 0},
                "out_start_ms": 3000,
                "out_end_ms": 5000,
            },
        ],
        "music": None,
        "duration_ms": 5000,
        "hash": "",
    }
    tl["hash"] = timeline_hash(tl)
    return tl


@pytest.mark.asyncio
async def test_resolve_raw_render_forwards_scene_fallbacks(monkeypatch):
    _reset_local_jobs()
    _reset_local_edits()
    monkeypatch.setattr(dispatch_config, "RENDER_SERVICE_URL", "https://render.test")
    monkeypatch.setattr(dispatch_config, "RENDER_SERVICE_SECRET", "test_secret_123")

    tl = _make_valid_timeline_dict()
    inputs_spec = {
        "input_take_1": {"storage_path": "abc/idea/1/take_1.webm", "kind": "video"},
        "input_take_2": {"storage_path": "abc/idea/2/take_2.webm", "kind": "video"},
        "input_mg_2": {"storage_path": "abc/idea/2/mg.html", "kind": "html"},
    }
    job = create_job(
        session_token="token_e2_03",
        idea_id="idea_e2_03",
        scene_n=None,
        kind="raw_render",
        input={"timeline": tl, "inputs": inputs_spec},
    )

    expected_fallbacks = [{"scene_n": 2, "used": "face", "reason": "empty_motion_graphic"}]

    def handle_render(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "ok": True,
                "storage_path": "abc/idea_e2_03/video/job_a1.mp4",
                "duration_ms": 5000,
                "bytes": 400000,
                "render_s": 10.0,
                "scene_marks_ms": [0, 3000],
                "converted": [],
                "scene_fallbacks": expected_fallbacks,
            },
        )

    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handle_render))

    async def mock_call(request):
        return await call_render_service(request, client=mock_client)

    monkeypatch.setattr("app.editing.dispatch.call_render_service", mock_call)

    out = await resolve_raw_render(job)
    assert out["scene_fallbacks"] == expected_fallbacks

    edit_row = get_edit("token_e2_03", "idea_e2_03")
    assert edit_row["raw_render"]["scene_fallbacks"] == expected_fallbacks


# ---------------------------------------------------------------------------
# 5. router.py: state exposes scene_fallbacks + the English warning text
# ---------------------------------------------------------------------------


class MockScript:
    """A locked 2-scene script (matches _make_valid_timeline_dict's scenes)."""

    def __init__(self) -> None:
        self.state = "locked"
        self.title = "Test Script"
        self.funnel_stage = "tofu"
        self.target_seconds = 10
        self.frame_zero = {
            "visual": "Initial hook visual",
            "on_screen_text": "Hook",
            "why_it_stops_the_scroll": "Catches attention",
        }
        self.scenes = [
            {
                "n": 1,
                "start_s": 0.0,
                "end_s": 5.0,
                "phase": "hook",
                "spoken_text": "Spoken text",
                "shot": "medium shot",
                "on_screen_text": "Text",
                "acting_note": "speak clearly",
                "sound": "upbeat",
                "asset_type": "a_roll",
            }
        ]

    def model_dump(self, mode: str = "json"):
        return {
            "state": self.state,
            "title": self.title,
            "funnel_stage": self.funnel_stage,
            "target_seconds": self.target_seconds,
            "frame_zero": self.frame_zero,
            "scenes": self.scenes,
        }


@pytest.fixture
def _router_setup(monkeypatch: pytest.MonkeyPatch):
    _reset_local_jobs()
    _reset_local_edits()
    monkeypatch.setattr(supabase_auth, "get_user_id", lambda auth: "u1")
    monkeypatch.setattr("app.guard.guard.get_or_create_user_session", lambda user_id: "tok_test")
    monkeypatch.setattr("app.tools.brand_brain.store.get_brand_brain", lambda tok: None)
    monkeypatch.setattr("app.editing.router._check_script", lambda tok, idea: MockScript())


def _prepare_raw_with_scene_fallbacks(idea_id: str, scene_fallbacks: list[dict]) -> None:
    from app.audiovisual.jobs import mark_done

    t = create_job("tok_test", idea_id, scene_n=1, kind="a_roll_take")
    mark_done(t["id"], output={"storage_path": "takes/s1.mp4", "duration_ms": 5000})
    tr = create_job(
        "tok_test", idea_id, scene_n=1, kind="transcript", input={"take_job_id": t["id"]}
    )
    mark_done(tr["id"], output={"words": [{"text": "hi", "start_ms": 0, "end_ms": 300}]})

    state = client.get(f"/api/editing/{idea_id}", headers=HEADERS).json()
    t_hash = state["timeline"]["hash"]
    edit_ver = state["edit_version"]
    save_edit(
        "tok_test",
        idea_id,
        {
            "raw_render": {
                "status": "done",
                "storage_path": "renders/raw.mp4",
                "timeline_hash": t_hash,
                "scene_fallbacks": scene_fallbacks,
            }
        },
        expected_version=edit_ver,
    )


def test_state_exposes_scene_fallbacks_and_face_warning(_router_setup):
    fallbacks = [{"scene_n": 3, "used": "face", "reason": "empty_motion_graphic"}]
    _prepare_raw_with_scene_fallbacks("idea_face", fallbacks)

    resp = client.get("/api/editing/idea_face", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()

    assert data["raw"]["scene_fallbacks"] == fallbacks
    assert (
        "Scene 3's motion graphic could not be drawn, so we used your face."
        in data["warnings"]
    )


def test_state_exposes_scene_fallbacks_and_image_warning(_router_setup):
    fallbacks = [{"scene_n": 5, "used": "image", "reason": "empty_motion_graphic"}]
    _prepare_raw_with_scene_fallbacks("idea_image", fallbacks)

    resp = client.get("/api/editing/idea_image", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()

    assert data["raw"]["scene_fallbacks"] == fallbacks
    assert (
        "Scene 5's motion graphic could not be drawn, so we used the AI image."
        in data["warnings"]
    )


def test_state_scene_fallbacks_defaults_to_empty_list(_router_setup):
    """A raw render with no fallbacks exposes an empty list, never omits the key."""
    _prepare_raw_with_scene_fallbacks("idea_clean", [])

    resp = client.get("/api/editing/idea_clean", headers=HEADERS)
    assert resp.status_code == 200
    data = resp.json()

    assert data["raw"]["scene_fallbacks"] == []
    assert data["warnings"] == []


# ---------------------------------------------------------------------------
# 6. editing.js: the warning banner is wired up, and stays valid JS
# ---------------------------------------------------------------------------


def test_node_check_editing_js():
    node_bin = shutil.which("node")
    assert node_bin is not None, "Node.js must be in PATH"
    res = subprocess.run(
        [node_bin, "--check", str(EDITING_JS)], capture_output=True, text=True, check=False
    )
    assert res.returncode == 0, f"node --check failed: {res.stderr}"


def test_editing_js_renders_state_warnings():
    content = EDITING_JS.read_text(encoding="utf-8")
    assert "state.warnings" in content
    assert "Editing-Warnings-Banner" in content
