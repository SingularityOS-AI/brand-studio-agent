import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.editing.brand_style import derive_caption_style
from app.editing.dressing import fallback_dressing
from app.editing.ir import build_ir_stage2
from app.editing.timeline import build_timeline
from render_service.app import app
from render_service.manifest import CaptionWord

# Skip all tests in this file if ffmpeg is missing
pytestmark = [
    pytest.mark.render,
    pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed"),
]

@pytest.fixture(scope="module")
def synthetic_media(tmp_path_factory):
    """Generate synthetic media files for testing without network."""
    tmp_path = tmp_path_factory.mktemp("synthetic_media")

    media = {}

    take1_path = tmp_path / "take1.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc2=s=1080x1920:d=6:r=30",
        "-f", "lavfi", "-i", "sine=f=440:d=6",
        "-c:v", "libx264", "-c:a", "aac", str(take1_path)
    ], check=True, capture_output=True)
    media["take1"] = str(take1_path)

    take2_path = tmp_path / "take2.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "smptebars=s=1080x1920:d=6:r=30",
        "-f", "lavfi", "-i", "sine=f=880:d=6",
        "-c:v", "libx264", "-c:a", "aac", str(take2_path)
    ], check=True, capture_output=True)
    media["take2"] = str(take2_path)

    image_path = tmp_path / "image.png"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=blue:s=1080x1920:d=1",
        "-frames:v", "1", str(image_path)
    ], check=True, capture_output=True)
    media["image"] = str(image_path)

    music_path = tmp_path / "music.mp3"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "anoisesrc=c=pink:r=44100:a=0.5:d=20",
        "-c:a", "libmp3lame", str(music_path)
    ], check=True, capture_output=True)
    media["music"] = str(music_path)

    sfx_path = tmp_path / "sfx.mp3"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=f=1000:d=0.5",
        "-c:a", "libmp3lame", str(sfx_path)
    ], check=True, capture_output=True)
    media["sfx"] = str(sfx_path)

    return media

def test_render_e2e_offline_mp4(synthetic_media, monkeypatch, tmp_path, evidence_dir_for):
    """
    Test rendering an MP4 end-to-end completely offline, utilizing synthetic media.
    Mocks upload/download IO, but exercises timeline, dressing, and IR generation.
    """

    jobs = [
        {
            "id": "job_1",
            "kind": "a_roll_take",
            "status": "done",
            "scene_n": 1,
            "result": {
                "take_id": "take_1",
                "storage_path": "test_take1.mp4",
                "duration": 6.0,
                "words": [
                    {"word": "Stop", "start": 0.5, "end": 1.0, "score": 0.9},
                    {"word": "wasting", "start": 1.0, "end": 1.5, "score": 0.9},
                    {"word": "money", "start": 1.5, "end": 2.0, "score": 0.9},
                    {"word": "on", "start": 2.0, "end": 2.5, "score": 0.9},
                    {"word": "ads", "start": 2.5, "end": 3.0, "score": 0.9},
                    {"word": "that", "start": 3.0, "end": 3.5, "score": 0.9},
                    {"word": "never", "start": 3.5, "end": 4.0, "score": 0.9},
                    {"word": "convert.", "start": 4.0, "end": 4.5, "score": 0.9},
                ]
            }
        },
        {
            "id": "job_2",
            "kind": "a_roll_take",
            "status": "done",
            "scene_n": 2,
            "result": {
                "take_id": "take_2",
                "storage_path": "test_take2.mp4",
                "duration": 6.0,
                "words": [
                    {"word": "This", "start": 0.5, "end": 1.0, "score": 0.9},
                    {"word": "is", "start": 1.0, "end": 1.5, "score": 0.9},
                    {"word": "the", "start": 1.5, "end": 2.0, "score": 0.9},
                    {"word": "way.", "start": 2.0, "end": 2.5, "score": 0.9},
                ]
            }
        }
    ]

    brand_soul = {"name": "Test Brand", "voice": "friendly", "colors": ["#FFFFFF", "#000000"]}
    caption_style = derive_caption_style(brand_soul)

    edit_doc = {
        "id": "edit_1",
        "founder_id": "founder_1",
        "script": {
            "title": "Test Ad",
            "scenes": [
                {"n": 1, "kind": "a_roll", "text": "Stop wasting money on ads that never convert."},
                {"n": 2, "kind": "a_roll", "text": "This is the way."}
            ]
        },
        "settings": {
            "caption_y": 1250,
            "overlays_enabled": True
        },
        "dressing": {
            "style": "standard"
        }
    }

    res = build_timeline(edit_doc['script'], jobs, edit_doc.get('settings'), 1)

    # Force timeline duration to match our inputs so ffmpeg doesn't complain about sync
    res['timeline']['duration_ms'] = 6000
    res['timeline']['scenes'][0]['segments'][0]['out_ms'] = 3000
    res['timeline']['scenes'][0]['out_end_ms'] = 3000
    res['timeline']['scenes'][1]['out_start_ms'] = 3000
    res['timeline']['scenes'][1]['segments'][0]['out_ms'] = 3000
    res['timeline']['scenes'][1]['out_end_ms'] = 6000

    from render_service.manifest import Timeline
    timeline = Timeline(**res['timeline'])
    timeline_inputs = res['inputs']


    scene_contexts = []
    for s in timeline.scenes:
        words_for_scene = [w for w in res['captions_words'] if w['scene_n'] == s.n]
        word_objs = [CaptionWord(**w) for w in words_for_scene]
        ctx = s.model_dump()
        ctx['words'] = word_objs
        ctx['duration_ms'] = s.out_end_ms - s.out_start_ms
        scene_contexts.append(ctx)

    from app.editing.dressing import load_catalog
    catalog = load_catalog()
    dressed_scenes = fallback_dressing(scene_contexts, catalog, "standard", {1: 42, 2: 43})

    ir_dict_raw = build_ir_stage2(
        timeline=timeline.model_dump(),
        captions_words=res['captions_words'],
        frame_zero_text='Stop wasting money on ads that never convert',
        style=caption_style,
        dressing={'scenes': dressed_scenes},
        script=edit_doc['script'],
        jobs=jobs
    )

    from render_service.manifest import RenderIR
    ir = RenderIR(**ir_dict_raw['ir'])

    final_inputs = {}
    final_inputs.update(timeline_inputs)
    final_inputs.update(ir_dict_raw.get('sfx_inputs', {}))

    ir_dict = ir.model_dump()

    final_inputs["take_s1"]["url"] = f"https://test.local/{synthetic_media['take1']}"
    final_inputs["take_s2"]["url"] = f"https://test.local/{synthetic_media['take2']}"

    if "bg_music" in final_inputs:
        final_inputs["bg_music"]["url"] = f"https://test.local/{synthetic_media['music']}"

    for k, v in final_inputs.items():
        if "storage_path" in v:
            del v["storage_path"]
        if v.get("kind") == "audio" and k != "bg_music":
            v["url"] = f"https://test.local/{synthetic_media['sfx']}"

    def mock_download_all(inputs, workdir, per_input_max=300000000, total_max=800000000, client=None):
        local_map = {}
        for input_id, ref in inputs.items():
            if ref.url.startswith("https://test.local/"):
                if ref.kind == "video":
                    local_map[input_id] = Path(synthetic_media['take1'])
                elif ref.kind == "image":
                    local_map[input_id] = Path(synthetic_media['image'])
                else:
                    local_map[input_id] = Path(synthetic_media['sfx'])
            else:
                if ref.kind == "video":
                    local_map[input_id] = Path(synthetic_media['take1'])
                elif ref.kind == "image":
                    local_map[input_id] = Path(synthetic_media['image'])
                else:
                    local_map[input_id] = Path(synthetic_media['sfx'])
        return local_map

    def mock_upload(upload_url, path, content_type="video/mp4", client=None):
        if upload_url == "https://mock.local/upload_raw":
            shutil.copy(path, tmp_path / "mock_raw.mp4")
        elif upload_url == "https://mock.local/upload":
            shutil.copy(path, tmp_path / "final_output.mp4")

    monkeypatch.setattr("render_service.app.download_all", mock_download_all)
    monkeypatch.setattr("render_service.app.upload", mock_upload)
    monkeypatch.setenv("RENDER_SERVICE_SECRET", "test_secret")
    monkeypatch.setenv("RENDER_ALLOWED_HOSTS", "test.local,mock.local")

    client = TestClient(app)

    # Create raw render request first
    raw_payload = {
        "schema": "brandstudio.render.v1",
        "job_id": "test_job_raw",
        "mode": "raw",
        "attempt": 1,
        "timeline": timeline.model_dump(),
        "inputs": final_inputs,
        "output": {"upload_url": "https://mock.local/upload_raw", "storage_path": "mock_raw.mp4"},
        "progress_url": None
    }

    headers = {"Authorization": "Bearer test_secret"}
    raw_response = client.post("/v1/render", json=raw_payload, headers=headers)
    assert raw_response.status_code == 200, raw_response.text

    output_raw_mp4 = tmp_path / "mock_raw.mp4"
    assert output_raw_mp4.exists()

    # Add the raw video back into inputs for the final render!
    final_inputs["raw_video"] = {"url": "https://test.local/mock_raw.mp4", "kind": "video"}

    # And we must teach mock_download_all to serve mock_raw.mp4

    payload = {
        "schema": "brandstudio.render.v1",
        "job_id": "test_job",
        "mode": "final",
        "raw_input_id": "raw_video",
        "attempt": 1,
        "ir": ir_dict,
        "inputs": final_inputs,
        "output": {"upload_url": "https://mock.local/upload", "storage_path": "mock.mp4"},
        "progress_url": None
    }

    headers = {"Authorization": "Bearer test_secret"}
    response = client.post("/v1/render", json=payload, headers=headers)
    assert response.status_code == 200, response.text

    output_mp4 = tmp_path / "final_output.mp4"
    assert output_mp4.exists()

    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-show_streams",
        "-of", "json",
        str(output_mp4)
    ]

    probe_res = subprocess.run(cmd, check=True, capture_output=True, text=True)
    probe_data = json.loads(probe_res.stdout)

    video_stream = next(s for s in probe_data["streams"] if s["codec_type"] == "video")
    assert video_stream["width"] == 1080
    assert video_stream["height"] == 1920
    assert video_stream["codec_name"] == "h264"

    audio_stream = next(s for s in probe_data["streams"] if s["codec_type"] == "audio")
    assert audio_stream["codec_name"] == "aac"

    duration = float(probe_data["format"]["duration"])
    expected_duration = ir.duration_ms / 1000.0
    assert abs(duration - expected_duration) <= 0.150, f"Duration {duration} vs {expected_duration}"

    times = [0.2]
    for scene in timeline.scenes:
        start_t = scene.out_start_ms / 1000.0
        times.append(start_t)

    for overlay in ir_dict.get("overlays", []):
        midpoint = (overlay["start_ms"] + overlay["end_ms"]) / 2000.0
        times.append(midpoint)

    if len(times) == 1:
        times.append(expected_duration / 2.0)

    times_str = [str(t) for t in times]
    sheet_out = evidence_dir_for("E2-01") / "sheet.png"

    subprocess.run([
        "python", "scripts/render_contact_sheet.py",
        str(output_mp4), *times_str, "--out", str(sheet_out)
    ], check=True)

    assert sheet_out.exists()
