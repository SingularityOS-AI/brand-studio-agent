"""
AI Image and Video Resolvers using Google GenAI / Vertex AI (Pieza 53).

Resolvers:
- resolve_ai_image: Gemini 3.1 Flash-Lite Image (5 credits, $0.0336 cost)
- resolve_ai_video: Veo 3.1 Lite (90 credits, $0.30 cost, resumable, max 1 per idea)
"""
from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

from google.genai import types

from app.audiovisual.config import (
    AV_IMAGE_LOCATION,
    AV_IMAGE_MODEL,
    AV_VIDEO_LOCATION,
    AV_VIDEO_MODEL,
    AV_VIDEO_POLL_INTERVAL,
    AV_VIDEO_TIMEOUT_SECONDS,
)
from app.audiovisual.genai_client import get_genai_client
from app.audiovisual.jobs import list_jobs, set_job_progress
from app.audiovisual.storage import upload_bytes

logger = logging.getLogger(__name__)

IMAGE_PROMPT_SUFFIX = (
    ", vertical 9:16 composition, photorealistic, no text, no captions, no logos, no watermarks"
)


async def resolve_ai_image(job: dict[str, Any]) -> dict[str, Any]:
    """
    Resolver for 'ai_image' job (Pieza 53):
    1. Uses AV_IMAGE_MODEL with 9:16 aspect ratio.
    2. Builds prompt with fixed suffix.
    3. Runs synchronously wrapped in asyncio.to_thread.
    4. Extracts inline image bytes and uploads to Supabase storage.
    5. Returns output dict with storage_path, mime, model_id, cost_usd 0.0336, prompt_used.
    If no image is returned (safety block, etc.), raises RuntimeError so worker marks failed.
    """
    input_data = job.get("input") or {}
    raw_prompt = (input_data.get("visual_prompt") or input_data.get("spoken_text") or "").strip()
    if raw_prompt:
        prompt_used = f"{raw_prompt}{IMAGE_PROMPT_SUFFIX}"
    else:
        prompt_used = f"cinematic scene{IMAGE_PROMPT_SUFFIX}"

    model_id = job.get("model_id") or AV_IMAGE_MODEL
    client = get_genai_client(AV_IMAGE_LOCATION)

    config = types.GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=types.ImageConfig(aspect_ratio="9:16"),
    )

    try:
        response = await asyncio.to_thread(
            client.models.generate_content,
            model=model_id,
            contents=prompt_used,
            config=config,
        )
    except Exception as e:
        logger.error(f"[ai_image] GenAI generate_content error: {e}")
        raise RuntimeError(f"Image generation failed: {e}") from e

    # Extract image bytes from response
    image_bytes: bytes | None = None
    mime_type: str = "image/png"
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            inline_data = getattr(part, "inline_data", None)
            if inline_data and getattr(inline_data, "data", None):
                data = inline_data.data
                if isinstance(data, str):
                    image_bytes = base64.b64decode(data)
                elif isinstance(data, bytes):
                    image_bytes = data
                if getattr(inline_data, "mime_type", None):
                    mime_type = inline_data.mime_type
                break
        if image_bytes:
            break

    if not image_bytes:
        reason = "No image returned in model response"
        if candidates:
            finish_reason = getattr(candidates[0], "finish_reason", None)
            if finish_reason:
                reason = f"Image generation blocked or failed: finish_reason={finish_reason}"
        prompt_feedback = getattr(response, "prompt_feedback", None)
        if prompt_feedback and getattr(prompt_feedback, "block_reason", None):
            reason = f"Image generation blocked: {prompt_feedback.block_reason}"
        raise RuntimeError(reason)

    storage_path = upload_bytes(
        session_token=job["session_token"],
        idea_id=job["idea_id"],
        scene_n=job.get("scene_n"),
        job_id=job["id"],
        data=image_bytes,
        mime=mime_type or "image/png",
    )

    return {
        "storage_path": storage_path,
        "mime": mime_type or "image/png",
        "model_id": model_id,
        "cost_usd": 0.0336,
        "prompt_used": prompt_used,
    }


async def resolve_ai_video(job: dict[str, Any]) -> dict[str, Any]:
    """
    Resolver for 'ai_video' job (Pieza 53):
    1. Enforces max 1 active AI video per idea.
    2. Resumable via operation_name in job output (never starts 2 operations for same job).
    3. Long-running operation with polling (up to 8 min timeout).
    4. Downloads video bytes (from video_bytes or GCS uri) and uploads to storage.
    5. Returns output dict with storage_path, mime, duration_s 6, model_id, cost_usd 0.30, prompt_used.
    """
    # 1. Check AI video limit per idea (only 1 active ai_video per script)
    existing_jobs = list_jobs(session_token=job["session_token"], idea_id=job["idea_id"])
    for j in existing_jobs:
        if j.get("id") != job["id"] and j.get("kind") == "ai_video":
            if j.get("status") in ("pending", "running", "done"):
                raise RuntimeError("AI video limit")

    model_id = job.get("model_id") or AV_VIDEO_MODEL
    client = get_genai_client(AV_VIDEO_LOCATION)

    output_data = job.get("output") or {}
    operation_name = output_data.get("operation_name")
    input_data = job.get("input") or {}
    prompt = input_data.get("visual_prompt") or input_data.get("spoken_text") or ""

    # 2. Reanudable: if operation_name is already known, query it instead of starting a new video
    if operation_name:
        logger.info(f"[ai_video] Resuming existing operation: {operation_name}")
        op_arg = types.GenerateVideosOperation(name=operation_name)
        try:
            operation = await asyncio.to_thread(client.operations.get, op_arg)
        except Exception as e:
            logger.error(f"[ai_video] Failed to get existing operation {operation_name}: {e}")
            raise RuntimeError(f"Failed to check existing video operation: {e}") from e
    else:
        config = types.GenerateVideosConfig(
            aspect_ratio="9:16",
            resolution="720p",
            duration_seconds=6,
            number_of_videos=1,
            generate_audio=False,
        )
        try:
            operation = await asyncio.to_thread(
                client.models.generate_videos,
                model=model_id,
                prompt=prompt,
                config=config,
            )
        except Exception as e:
            logger.error(f"[ai_video] Failed to start generate_videos: {e}")
            raise RuntimeError(f"Failed to start video generation: {e}") from e

        operation_name = getattr(operation, "name", None)
        if operation_name:
            set_job_progress(job["id"], {"operation_name": operation_name})

    # 3. Polling loop with timeout
    start_time = asyncio.get_running_loop().time()
    poll_interval = AV_VIDEO_POLL_INTERVAL
    timeout_s = AV_VIDEO_TIMEOUT_SECONDS

    while not getattr(operation, "done", False):
        elapsed = asyncio.get_running_loop().time() - start_time
        if elapsed >= timeout_s:
            raise RuntimeError("Video generation timed out")

        await asyncio.sleep(poll_interval)

        elapsed = asyncio.get_running_loop().time() - start_time
        if elapsed >= timeout_s:
            raise RuntimeError("Video generation timed out")

        op_arg = (
            operation
            if hasattr(operation, "name") and getattr(operation, "name")
            else types.GenerateVideosOperation(name=operation_name)
        )
        try:
            operation = await asyncio.to_thread(client.operations.get, op_arg)
        except Exception as e:
            logger.warning(f"[ai_video] Polling operation check error: {e}")
            # If polling error, check timeout before retrying next iteration
            if asyncio.get_running_loop().time() - start_time >= timeout_s:
                raise RuntimeError("Video generation timed out")

    if getattr(operation, "error", None):
        raise RuntimeError(f"Video generation operation failed: {operation.error}")

    # 4. Extract video bytes
    op_response = getattr(operation, "response", None) or getattr(operation, "result", None)
    if not op_response:
        raise RuntimeError("No video response received from operation")

    generated_videos = getattr(op_response, "generated_videos", None) or []
    if not generated_videos:
        reasons = getattr(op_response, "rai_media_filtered_reasons", None)
        msg = f"No videos generated: {reasons}" if reasons else "No videos generated in operation response"
        raise RuntimeError(msg)

    first_video = (
        generated_videos[0].video
        if hasattr(generated_videos[0], "video")
        else generated_videos[0]
    )
    video_bytes = getattr(first_video, "video_bytes", None)

    if not video_bytes:
        uri = getattr(first_video, "uri", None)
        if uri:
            try:
                video_bytes = await asyncio.to_thread(client.files.download, file=uri)
            except Exception as e:
                raise RuntimeError(f"Failed to download video from URI: {e}") from e
        else:
            raise RuntimeError("Operation response contained neither video_bytes nor uri")

    if not video_bytes:
        raise RuntimeError("Empty video bytes downloaded")

    # 5. Upload bytes
    storage_path = upload_bytes(
        session_token=job["session_token"],
        idea_id=job["idea_id"],
        scene_n=job.get("scene_n"),
        job_id=job["id"],
        data=video_bytes,
        mime="video/mp4",
    )

    return {
        "storage_path": storage_path,
        "mime": "video/mp4",
        "duration_s": 6,
        "model_id": model_id,
        "cost_usd": 0.30,
        "prompt_used": prompt,
        "operation_name": operation_name,
    }
