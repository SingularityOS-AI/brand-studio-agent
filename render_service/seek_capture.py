"""Seek-capture module for motion graphics rendering (Piece E2-02)."""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

from render_service.motion import chromium_path

logger = logging.getLogger(__name__)

VENDOR_DIR = Path(__file__).parent / "vendor"
GSAP_VENDOR_PATH = VENDOR_DIR / "gsap.min.js"


def prepare_html(html_path: Path | str, out_dir: Path | str) -> Path:
    """Prepares HTML for local rendering by rewriting CDN GSAP to vendored file."""
    html_path = Path(html_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    content = html_path.read_text(encoding="utf-8")

    # Copy vendored gsap.min.js into out_dir for local relative script loading
    local_gsap = out_dir / "gsap.min.js"
    if GSAP_VENDOR_PATH.is_file():
        shutil.copy2(GSAP_VENDOR_PATH, local_gsap)
    else:
        logger.warning("Vendored GSAP file not found at %s", GSAP_VENDOR_PATH)

    # Rewrite any CDN script tag for GSAP to the local vendored file
    # Matches patterns like <script src="https://cdn.jsdelivr.net/.../gsap...js"></script>
    gsap_cdn_pattern = re.compile(
        r'<script\s+[^>]*src=["\']https?://[^"\']*gsap[^"\']*["\'][^>]*>\s*</script>',
        re.IGNORECASE,
    )

    rewritten_content = gsap_cdn_pattern.sub(
        '<script src="gsap.min.js"></script>',
        content,
    )

    prepared_file = out_dir / "prepared_seek.html"
    prepared_file.write_text(rewritten_content, encoding="utf-8")
    return prepared_file


def capture(
    html_path: Path | str,
    out_dir: Path | str,
    *,
    width: int,
    height: int,
    fps: int = 30,
    transparent: bool = False,
    max_anim_s: float = 3.0,
) -> list[Path]:
    """
    Renders an HTML composition step-by-step using Chromium seek-capture.

    Args:
        html_path: Path to the motion graphic HTML file.
        out_dir: Destination directory for captured PNG frames.
        width: Viewport and render width (e.g. 1080).
        height: Viewport and render height (e.g. 1920).
        fps: Frames per second (default 30).
        transparent: Whether to omit background for transparent overlays.
        max_anim_s: Maximum animation duration in seconds to capture (default 3.0).

    Returns:
        List of Path objects for captured frames in chronological order.
        The last PNG is the hold frame.
    """
    html_path = Path(html_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not html_path.is_file():
        raise FileNotFoundError(f"HTML composition not found: {html_path}")

    chrom_exe = chromium_path()
    if not chrom_exe:
        raise RuntimeError("Chromium executable not found for seek-capture")

    prepared_html = prepare_html(html_path, out_dir)

    frames: list[Path] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=chrom_exe,
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--hide-scrollbars",
                "--allow-file-access-from-files",
            ],
        )
        try:
            context = browser.new_context(
                viewport={"width": width, "height": height},
                device_scale_factor=1,
            )
            page = context.new_page()

            # Ensure any CDN requests for GSAP are fulfilled locally
            if GSAP_VENDOR_PATH.is_file():
                page.route(
                    "**/*gsap*.js",
                    lambda route: route.fulfill(
                        path=str(GSAP_VENDOR_PATH),
                        content_type="application/javascript",
                    ),
                )

            page.goto(prepared_html.resolve().as_uri(), wait_until="load")

            if transparent:
                page.evaluate(
                    """() => {
                        document.documentElement.style.background = 'transparent';
                        if (document.body) {
                            document.body.style.background = 'transparent';
                        }
                    }"""
                )

            # Wait for window.__timelines to be populated
            page.wait_for_function(
                "() => window.__timelines && Object.keys(window.__timelines).length > 0",
                timeout=10000,
            )

            # Compute D = min(longest tl.duration(), max_anim_s)
            longest_duration: Any = page.evaluate(
                """() => {
                    const tls = Object.values(window.__timelines || {});
                    let maxD = 0;
                    for (const tl of tls) {
                        if (typeof tl.duration === 'function') {
                            maxD = Math.max(maxD, tl.duration());
                        }
                    }
                    return maxD;
                }"""
            )
            anim_duration = min(float(longest_duration or 0.0), max_anim_s)

            # Step 1/fps: call tl.seek(t, false) on every timeline and screenshot
            num_frames = max(1, round(anim_duration * fps) + 1)

            for frame_idx in range(num_frames):
                t = min(frame_idx / fps, anim_duration) if anim_duration > 0 else 0.0
                page.evaluate(
                    """(t) => {
                        const tls = Object.values(window.__timelines || {});
                        for (const tl of tls) {
                            if (typeof tl.seek === 'function') {
                                tl.seek(t, false);
                            }
                        }
                    }""",
                    t,
                )
                frame_path = out_dir / f"frame_{frame_idx:05d}.png"
                page.screenshot(path=str(frame_path), omit_background=transparent)
                frames.append(frame_path)

        finally:
            browser.close()

    if not frames:
        raise RuntimeError("Seek-capture produced no frames")

    return frames
