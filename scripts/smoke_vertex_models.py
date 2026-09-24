"""
Smoke test script for Vertex AI models (google-genai SDK).
PIEZA 53 — Executed ONLY by the Captain / CEO to confirm real model IDs in production.
DO NOT RUN IN CI / AUTOMATED TEST PIPELINES (incurs real Vertex billing).
"""
from __future__ import annotations

import argparse
import base64
import sys
import time

from google.genai import types

from app.audiovisual.config import AV_IMAGE_LOCATION, AV_IMAGE_MODEL, AV_VIDEO_LOCATION, AV_VIDEO_MODEL
from app.audiovisual.genai_client import get_genai_client


def smoke_image() -> None:
    """Generate 1 test image and print model_id, size in bytes, and duration."""
    prompt = "a calm clinic waiting room"
    model_id = AV_IMAGE_MODEL
    client = get_genai_client(AV_IMAGE_LOCATION)

    config = types.GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=types.ImageConfig(aspect_ratio="9:16"),
    )

    t0 = time.time()
    response = client.models.generate_content(
        model=model_id,
        contents=prompt,
        config=config,
    )
    elapsed = time.time() - t0

    image_bytes: bytes | None = None
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
                break
        if image_bytes:
            break

    if not image_bytes:
        print(f"FAILED: No image in response from model {model_id}")
        sys.exit(1)

    print(f"model_id: {model_id} | size_bytes: {len(image_bytes)} | duration: {elapsed:.2f}s")


def smoke_video() -> None:
    """Generate 1 test video (6s) and print model_id, size in bytes, and duration."""
    prompt = "a calm clinic waiting room"
    model_id = AV_VIDEO_MODEL
    client = get_genai_client(AV_VIDEO_LOCATION)

    config = types.GenerateVideosConfig(
        aspect_ratio="9:16",
        resolution="720p",
        duration_seconds=6,
        number_of_videos=1,
        generate_audio=False,
    )

    t0 = time.time()
    operation = client.models.generate_videos(
        model=model_id,
        prompt=prompt,
        config=config,
    )

    while not getattr(operation, "done", False):
        time.sleep(10)
        operation = client.operations.get(operation)

    if getattr(operation, "error", None):
        print(f"FAILED: Video generation failed: {operation.error}")
        sys.exit(1)

    elapsed = time.time() - t0

    op_response = getattr(operation, "response", None) or getattr(operation, "result", None)
    if not op_response:
        print("FAILED: No operation response received")
        sys.exit(1)

    generated_videos = getattr(op_response, "generated_videos", None) or []
    if not generated_videos:
        print("FAILED: No videos generated in response")
        sys.exit(1)

    first_video = (
        generated_videos[0].video
        if hasattr(generated_videos[0], "video")
        else generated_videos[0]
    )
    video_bytes = getattr(first_video, "video_bytes", None)

    if not video_bytes:
        uri = getattr(first_video, "uri", None)
        if uri:
            video_bytes = client.files.download(file=uri)
        else:
            print("FAILED: No video bytes or URI in response")
            sys.exit(1)

    print(f"model_id: {model_id} | size_bytes: {len(video_bytes)} | duration: {elapsed:.2f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test real Vertex GenAI models (Captain only)")
    parser.add_argument("--image", action="store_true", help="Generate 1 test image with AV_IMAGE_MODEL")
    parser.add_argument("--video", action="store_true", help="Generate 1 test video with AV_VIDEO_MODEL")
    args = parser.parse_args()

    if not args.image and not args.video:
        parser.print_help()
        sys.exit(1)

    if args.image:
        smoke_image()
    if args.video:
        smoke_video()


if __name__ == "__main__":
    main()
