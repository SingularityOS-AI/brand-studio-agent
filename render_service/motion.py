"""Motion graphics conversion module (PIEZA 75)."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def chromium_path() -> str | None:
    for env_var in ("PUPPETEER_EXECUTABLE_PATH", "CHROME_PATH"):
        val = os.getenv(env_var)
        if val and os.path.isfile(val):
            return val

    if os.path.isfile("/usr/bin/chromium"):
        return "/usr/bin/chromium"

    for name in ("chromium", "chromium-browser", "chrome", "google-chrome"):
        found = shutil.which(name)
        if found:
            return found

    return None


def hyperframes_cmd() -> list[str] | None:
    hf = shutil.which("hyperframes")
    if hf:
        return [hf]

    npx = shutil.which("npx")
    if npx:
        return [npx, "hyperframes@0.8.75"]

    return None


def convert_html(
    html_path: Path,
    out_path: Path,
    duration_s: float,
    workdir: Path,
    timeout_s: int = 120,
) -> Path:
    """Converts a motion graphic HTML page to 1080x1920 30fps MP4 video."""
    html_path = Path(html_path)
    out_path = Path(out_path)
    workdir = Path(workdir)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Primary path: HyperFrames CLI
    hf_cmd = hyperframes_cmd()
    if hf_cmd:
        mg_dir = workdir / "mg"
        mg_dir.mkdir(parents=True, exist_ok=True)
        index_html = mg_dir / "index.html"
        shutil.copy2(html_path, index_html)

        cmd = hf_cmd + [
            "render",
            str(mg_dir),
            "--output",
            str(out_path),
            "--fps",
            "30",
            "--quality",
            "standard",
            "--workers",
            "1",
        ]
        try:
            subprocess.run(
                cmd,
                check=True,
                timeout=timeout_s,
                capture_output=True,
            )
            if out_path.is_file() and out_path.stat().st_size > 0:
                return out_path
        except Exception as e:
            logger.warning(
                "HyperFrames render failed, falling back to Chromium screenshot: %s",
                type(e).__name__,
            )

    # 2. Fallback path: Chromium screenshot + FFmpeg loop
    chrom_exe = chromium_path()
    ffmpeg_exe = shutil.which("ffmpeg")

    if chrom_exe and ffmpeg_exe:
        logger.info("Using Chromium + FFmpeg fallback for motion graphic conversion")
        png_path = workdir / "fallback_mg.png"
        file_url = html_path.resolve().as_uri()
        half_budget_ms = int((duration_s / 2.0) * 1000)

        # --no-sandbox: the container runs as a non-root user without user
        # namespaces, where Chromium refuses to start sandboxed. It only ever
        # loads our own motion templates from the local temp dir.
        chrom_cmd = [
            chrom_exe,
            "--headless=new",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--hide-scrollbars",
            "--window-size=1080,1920",
            f"--virtual-time-budget={half_budget_ms}",
            f"--screenshot={png_path}",
            file_url,
        ]
        try:
            subprocess.run(
                chrom_cmd,
                check=True,
                timeout=timeout_s,
                capture_output=True,
            )
            if png_path.is_file() and png_path.stat().st_size > 0:
                ffmpeg_cmd = [
                    ffmpeg_exe,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-loop",
                    "1",
                    "-i",
                    str(png_path),
                    "-t",
                    f"{duration_s:.3f}",
                    "-vf",
                    "scale=1080:1920,format=yuv420p",
                    "-r",
                    "30",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "23",
                    "-y",
                    str(out_path),
                ]
                subprocess.run(
                    ffmpeg_cmd,
                    check=True,
                    timeout=timeout_s,
                    capture_output=True,
                )
                if out_path.is_file() and out_path.stat().st_size > 0:
                    return out_path
        except Exception as e:
            logger.warning("Chromium fallback render failed: %s", type(e).__name__)

    # 3. Both failed or no converters available
    raise RuntimeError(
        "Motion graphic HTML conversion failed: converters unavailable or execution failed"
    )
