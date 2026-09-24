"""
Tests for PIEZA 53: AI Image and Video Generation with Vertex AI (google-genai).

Verifies:
1. resolve_ai_image with inline_data response -> uploads bytes, returns storage_path and cost_usd=0.0336.
2. resolve_ai_image without image in response -> raises RuntimeError, no credits charged.
3. resolve_ai_video with polling (2 polls) -> uploads video, returns cost_usd=0.30.
4. Resume: job with existing operation_name -> generate_videos NOT called again.
5. Timeout in video polling -> raises RuntimeError, job marked failed, no credits charged.
6. Worker process_one_job for ai_video -> deduct_credits called exactly once with 90 credits when done.

SDK is mocked (network blocked in conftest.py).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.audiovisual.jobs import (
    _reset_local_jobs,
    create_job,
    get_job,
)
from app.audiovisual.worker import (
    RESOLVERS,
    process_one_job,
    register_default_resolvers,
)
from app.audiovisual.ai_generation import (
    resolve_ai_image,
    resolve_ai_video,
)
from app.guard import guard


@pytest.fixture(autouse=True)
def reset_audiovisual_state():
    """Reset jobs, resolvers, sessions, and parches for clean test isolation."""
    _reset_local_jobs()
    RESOLVERS.clear()
    register_default_resolvers()
    guard._sessions.clear()
    with patch("app.scripting.scripts._get_script_client", return_value=None):
        yield
    _reset_local_jobs()
    RESOLVERS.clear()
    guard._sessions.clear()


@pytest.fixture
def mock_session():
    """Create a test session with credits."""
    token = "sess_p53_test_token"
    guard._sessions[token] = {
        "created_at": 1000.0,
        "last_activity": 1000.0,
        "initial_credits": 250,
        "remaining_credits": 250,
        "ip": "127.0.0.1",
        "email": "test@singularityos.com",
    }
    return token


# ---------------------------------------------------------------------------
# 1. AI IMAGE TESTS
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ai_image_success_with_inline_data(mock_session):
    """Test 1: resolve_ai_image with inline_data response uploads bytes and returns correct cost."""
    session_token = mock_session
    idea_id = "idea_p53_img_success"

    # Create a mock response with inline_data containing image bytes
    mock_inline_data = MagicMock()
    mock_inline_data.data = b"fake_png_bytes_001"
    mock_inline_data.mime_type = "image/png"

    mock_part = MagicMock()
    mock_part.inline_data = mock_inline_data

    mock_content = MagicMock()
    mock_content.parts = [mock_part]

    mock_candidate = MagicMock()
    mock_candidate.content = mock_content
    mock_candidate.finish_reason = None

    mock_response = MagicMock()
    mock_response.candidates = [mock_candidate]
    mock_response.prompt_feedback = None

    # Mock the genai client and upload_bytes
    mock_client = MagicMock()
    mock_client.models.generate_content = MagicMock(return_value=mock_response)

    with patch("app.audiovisual.ai_generation.get_genai_client", return_value=mock_client):
        with patch("app.audiovisual.ai_generation.upload_bytes", return_value="hash/idea/1/img_123.png") as mock_upload:
            job = create_job(
                session_token=session_token,
                idea_id=idea_id,
                scene_n=1,
                kind="ai_image",
                credits=5,
                cost_usd=0.0336,
                input={"visual_prompt": "A futuristic office"},
            )

            result = await resolve_ai_image(job)

            # Verify upload_bytes was called with correct mime
            mock_upload.assert_called_once()
            call_args = mock_upload.call_args
            assert call_args.kwargs["mime"] == "image/png"
            assert call_args.kwargs["data"] == b"fake_png_bytes_001"

            # Verify output
            assert result["storage_path"] == "hash/idea/1/img_123.png"
            assert result["mime"] == "image/png"
            assert result["cost_usd"] == 0.0336
            assert "prompt_used" in result
            assert "futuristic office" in result["prompt_used"]
            assert "vertical 9:16" in result["prompt_used"]


@pytest.mark.asyncio
async def test_ai_image_no_image_raises_exception(mock_session):
    """Test 2: resolve_ai_image without image in response raises RuntimeError (job will be marked failed, 0 credits)."""
    session_token = mock_session
    idea_id = "idea_p53_img_fail"

    # Mock response with empty candidates (no image)
    mock_response = MagicMock()
    mock_response.candidates = []
    mock_response.prompt_feedback = None

    mock_client = MagicMock()
    mock_client.models.generate_content = MagicMock(return_value=mock_response)

    with patch("app.audiovisual.ai_generation.get_genai_client", return_value=mock_client):
        with patch("app.audiovisual.ai_generation.upload_bytes") as mock_upload:
            job = create_job(
                session_token=session_token,
                idea_id=idea_id,
                scene_n=1,
                kind="ai_image",
                credits=5,
                cost_usd=0.0336,
                input={"visual_prompt": "A dark scene"},
            )

            with pytest.raises(RuntimeError, match="No image returned"):
                await resolve_ai_image(job)

            # upload_bytes should NOT be called
            mock_upload.assert_not_called()


# ---------------------------------------------------------------------------
# 3. AI VIDEO TESTS
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ai_video_success_with_polling(mock_session):
    """Test 3: resolve_ai_video polls operation and returns video after completion, cost_usd=0.30."""
    session_token = mock_session
    idea_id = "idea_p53_vid_poll"

    # Create mock video bytes result
    mock_video = MagicMock()
    mock_video.video_bytes = b"fake_mp4_video_bytes"
    mock_video.uri = None

    mock_generated_video = MagicMock()
    mock_generated_video.video = mock_video

    mock_op_response = MagicMock()
    mock_op_response.generated_videos = [mock_generated_video]

    # First poll: not done
    mock_operation_pending = MagicMock()
    mock_operation_pending.done = False
    mock_operation_pending.name = "operations/veo-op-123"
    mock_operation_pending.error = None
    mock_operation_pending.response = None

    # Second poll: done with video
    mock_operation_done = MagicMock()
    mock_operation_done.done = True
    mock_operation_done.name = "operations/veo-op-123"
    mock_operation_done.error = None
    mock_operation_done.response = mock_op_response

    mock_client = MagicMock()
    mock_client.models.generate_videos = MagicMock(return_value=mock_operation_pending)
    mock_client.operations.get = MagicMock(side_effect=[mock_operation_pending, mock_operation_done])

    with patch("app.audiovisual.ai_generation.get_genai_client", return_value=mock_client):
        with patch("app.audiovisual.ai_generation.upload_bytes", return_value="hash/idea/1/vid_123.mp4") as mock_upload:
            with patch("asyncio.sleep", new_callable=AsyncMock):
                job = create_job(
                    session_token=session_token,
                    idea_id=idea_id,
                    scene_n=1,
                    kind="ai_video",
                    credits=90,
                    cost_usd=0.30,
                    input={"visual_prompt": "A robot dancing"},
                )

                result = await resolve_ai_video(job)

                # Verify generate_videos was called once
                mock_client.models.generate_videos.assert_called_once()

                # Verify operations.get was called (polling)
                assert mock_client.operations.get.call_count >= 1

                # Verify upload_bytes was called with video/mp4
                mock_upload.assert_called_once()
                call_args = mock_upload.call_args
                assert call_args.kwargs["mime"] == "video/mp4"

                # Verify output
                assert result["storage_path"] == "hash/idea/1/vid_123.mp4"
                assert result["mime"] == "video/mp4"
                assert result["cost_usd"] == 0.30
                assert result["duration_s"] == 6
                assert "operation_name" in result


@pytest.mark.asyncio
async def test_ai_video_resume_existing_operation(mock_session):
    """Test 4: Job with existing operation_name -> generate_videos NOT called, only polls existing operation."""
    session_token = mock_session
    idea_id = "idea_p53_vid_resume"

    # Create mock video bytes result
    mock_video = MagicMock()
    mock_video.video_bytes = b"resumed_video_bytes"
    mock_video.uri = None

    mock_generated_video = MagicMock()
    mock_generated_video.video = mock_video

    mock_op_response = MagicMock()
    mock_op_response.generated_videos = [mock_generated_video]

    mock_operation_done = MagicMock()
    mock_operation_done.done = True
    mock_operation_done.name = "operations/existing-op-456"
    mock_operation_done.error = None
    mock_operation_done.response = mock_op_response

    mock_client = MagicMock()
    mock_client.models.generate_videos = MagicMock()
    mock_client.operations.get = MagicMock(return_value=mock_operation_done)

    with patch("app.audiovisual.ai_generation.get_genai_client", return_value=mock_client):
        with patch("app.audiovisual.ai_generation.upload_bytes", return_value="hash/idea/1/vid_resumed.mp4"):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                # Create job with existing operation_name in output
                job = create_job(
                    session_token=session_token,
                    idea_id=idea_id,
                    scene_n=1,
                    kind="ai_video",
                    credits=90,
                    cost_usd=0.30,
                    input={"visual_prompt": "A dancer"},
                )
                # Simulate resumable state by setting operation_name in output
                from app.audiovisual.jobs import set_job_progress
                set_job_progress(job["id"], {"operation_name": "operations/existing-op-456"})

                result = await resolve_ai_video(get_job(job["id"]))

                # Verify generate_videos was NOT called (resumed operation)
                mock_client.models.generate_videos.assert_not_called()

                # Verify operations.get WAS called to check existing operation
                mock_client.operations.get.assert_called()

                # Verify result
                assert result["storage_path"] == "hash/idea/1/vid_resumed.mp4"
                assert result["cost_usd"] == 0.30


@pytest.mark.asyncio
async def test_ai_video_timeout_raises_exception(mock_session):
    """Test 5: Video polling timeout -> RuntimeError, job should be marked failed, 0 credits."""
    session_token = mock_session
    idea_id = "idea_p53_vid_timeout"

    # Operation never completes
    mock_operation_pending = MagicMock()
    mock_operation_pending.done = False
    mock_operation_pending.name = "operations/veo-op-timeout"
    mock_operation_pending.error = None

    mock_client = MagicMock()
    mock_client.models.generate_videos = MagicMock(return_value=mock_operation_pending)
    mock_client.operations.get = MagicMock(return_value=mock_operation_pending)

    with patch("app.audiovisual.ai_generation.get_genai_client", return_value=mock_client):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            with patch("app.audiovisual.ai_generation.AV_VIDEO_TIMEOUT_SECONDS", 0.01):  # Fast timeout
                job = create_job(
                    session_token=session_token,
                    idea_id=idea_id,
                    scene_n=1,
                    kind="ai_video",
                    credits=90,
                    cost_usd=0.30,
                    input={"visual_prompt": "Slow motion scene"},
                )

                with pytest.raises(RuntimeError, match="timed out"):
                    await resolve_ai_video(job)


@pytest.mark.asyncio
async def test_worker_ai_video_charges_exactly_90_once(mock_session):
    """Test 6: With worker process_one_job: ai_video that completes charges exactly 90 credits once."""
    session_token = mock_session
    idea_id = "idea_p53_worker_charge"

    # Set up credits
    guard._sessions[session_token]["remaining_credits"] = 250

    # Create mock video bytes
    mock_video = MagicMock()
    mock_video.video_bytes = b"final_video_bytes"
    mock_video.uri = None

    mock_generated_video = MagicMock()
    mock_generated_video.video = mock_video

    mock_op_response = MagicMock()
    mock_op_response.generated_videos = [mock_generated_video]

    mock_operation_done = MagicMock()
    mock_operation_done.done = True
    mock_operation_done.name = "operations/veo-op-worker"
    mock_operation_done.error = None
    mock_operation_done.response = mock_op_response

    mock_client = MagicMock()
    mock_client.models.generate_videos = MagicMock(return_value=mock_operation_done)
    mock_client.operations.get = MagicMock(return_value=mock_operation_done)

    with patch("app.audiovisual.ai_generation.get_genai_client", return_value=mock_client):
        with patch("app.audiovisual.ai_generation.upload_bytes", return_value="hash/idea/1/vid_worker.mp4"):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with patch("app.audiovisual.worker.guard.deduct_credits") as mock_deduct:
                    mock_deduct.return_value = None  # Success

                    job = create_job(
                        session_token=session_token,
                        idea_id=idea_id,
                        scene_n=1,
                        kind="ai_video",
                        credits=90,
                        cost_usd=0.30,
                        input={"visual_prompt": "Final scene"},
                    )

                    # Process the job through the worker
                    claimed = await process_one_job()
                    assert claimed is True

                    # Verify deduct_credits was called exactly once with 90
                    mock_deduct.assert_called_once()
                    call_args = mock_deduct.call_args
                    assert call_args.args[0] == session_token  # First positional arg is session_token
                    assert call_args.kwargs["amount"] == 90

                    # Verify job is done
                    final_job = get_job(job["id"])
                    assert final_job["status"] == "done"
                    assert final_job["charged"] is True


@pytest.mark.asyncio
async def test_worker_ai_video_fails_no_charge(mock_session):
    """Test: With worker process_one_job: ai_video that fails does NOT charge credits."""
    session_token = mock_session
    idea_id = "idea_p53_worker_fail"

    # Set up credits
    guard._sessions[session_token]["remaining_credits"] = 250

    mock_client = MagicMock()
    mock_client.models.generate_videos = MagicMock(side_effect=RuntimeError("Generation failed"))

    with patch("app.audiovisual.ai_generation.get_genai_client", return_value=mock_client):
        with patch("app.audiovisual.worker.guard.deduct_credits") as mock_deduct:
            job = create_job(
                session_token=session_token,
                idea_id=idea_id,
                scene_n=1,
                kind="ai_video",
                credits=90,
                cost_usd=0.30,
                input={"visual_prompt": "Bad prompt"},
            )

            # Process the job through the worker
            claimed = await process_one_job()
            assert claimed is True

            # Verify deduct_credits was NOT called
            mock_deduct.assert_not_called()

            # Verify job is failed
            final_job = get_job(job["id"])
            assert final_job["status"] == "failed"
            assert final_job["charged"] is False
