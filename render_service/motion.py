"""Motion graphics conversion module (PIEZA 75 / E2-02)."""

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

    if os.name == "nt":
        windows_paths = [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        ]
        for wp in windows_paths:
            if os.path.isfile(wp):
                return wp

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
    timeout_s: int = 60,
) -> Path:
    """
    Converts a motion graphic HTML page to 1080x1920 30fps MP4 video.

    Execution order:
    1. Seek-capture first: frame-by-frame Chromium seek + FFmpeg hold (mg_path=seek)
    2. HyperFrames CLI fallback (mg_path=hyperframes)
    3. Last-resort still screenshot: tl.progress(1) + FFmpeg loop (mg_path=still)
    """
    html_path = Path(html_path)
    out_path = Path(out_path)
    workdir = Path(workdir)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    workdir.mkdir(parents=True, exist_ok=True)

    ffmpeg_exe = shutil.which("ffmpeg")

    # 1. Primary path: Seek-capture
    try:
        from render_service.seek_capture import capture as seek_capture_fn

        frames_dir = workdir / "seek_frames"
        frames_dir.mkdir(parents=True, exist_ok=True)

        frames = seek_capture_fn(
            html_path=html_path,
            out_dir=frames_dir,
            width=1080,
            height=1920,
            fps=30,
            transparent=False,
            max_anim_s=3.0,
        )

        if not ffmpeg_exe:
            raise RuntimeError("ffmpeg executable not found on PATH")

        if not frames:
            raise RuntimeError("seek_capture returned no frames")

        num_frames = len(frames)
        fps = 30
        anim_duration = (num_frames - 1) / fps if num_frames > 1 else 0.0
        hold_duration = max(0.0, duration_s - anim_duration)

        if num_frames == 1:
            ffmpeg_cmd = [
                ffmpeg_exe,
                "-hide_banner",
                "-loglevel",
                "error",
                "-loop",
                "1",
                "-i",
                str(frames[0]),
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
        else:
            pattern = str(frames_dir / "frame_%05d.png")
            vf_filter = (
                f"tpad=stop_mode=clone:stop_duration={hold_duration:.3f},"
                f"fps={fps},scale=1080:1920,format=yuv420p"
            )
            ffmpeg_cmd = [
                ffmpeg_exe,
                "-hide_banner",
                "-loglevel",
                "error",
                "-framerate",
                str(fps),
                "-i",
                pattern,
                "-vf",
                vf_filter,
                "-t",
                f"{duration_s:.3f}",
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
            logger.info("Motion graphic conversion succeeded (mg_path=seek)")
            return out_path
    except Exception as e:
        logger.warning(
            "Seek-capture failed, falling back to HyperFrames: %s",
            e,
        )

    # 2. Secondary path: HyperFrames CLI
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
                logger.info("Motion graphic conversion succeeded (mg_path=hyperframes)")
                return out_path
        except Exception as e:
            logger.warning(
                "HyperFrames render failed, falling back to Chromium screenshot: %s",
                e,
            )

    # 3. Fallback path: last-resort still screenshot with tl.progress(1)
    chrom_exe = chromium_path()

    if chrom_exe and ffmpeg_exe:
        logger.info("Attempting last-resort still screenshot (mg_path=still)")
        png_path = workdir / "fallback_mg.png"

        still_captured = False

        # Try Playwright to ensure tl.progress(1) runs cleanly
        try:
            from playwright.sync_api import sync_playwright
            from render_service.seek_capture import GSAP_VENDOR_PATH, prepare_html

            prepared_html = prepare_html(html_path, workdir / "prepared_still")
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
                    page = browser.new_page(viewport={"width": 1080, "height": 1920})
                    if GSAP_VENDOR_PATH.is_file():
                        page.route(
                            "**/*gsap*.js",
                            lambda route: route.fulfill(
                                path=str(GSAP_VENDOR_PATH),
                                content_type="application/javascript",
                            ),
                        )
                    page.goto(prepared_html.resolve().as_uri(), wait_until="load")
                    page.wait_for_function(
                        "() => window.__timelines && Object.keys(window.__timelines).length > 0",
                        timeout=5000,
                    )
                    page.evaluate(
                        """() => {
                            const tls = Object.values(window.__timelines || {});
                            for (const tl of tls) {
                                if (typeof tl.progress === 'function') {
                                    tl.progress(1);
                                }
                            }
                        }"""
                    )
                    page.screenshot(path=str(png_path), omit_background=False)
                    still_captured = png_path.is_file() and png_path.stat().st_size > 0
                finally:
                    browser.close()
        except Exception as e:
            logger.warning(
                "Playwright still capture failed: %s; trying modified HTML via CLI", e
            )

        if not still_captured:
            # Fallback to Chromium CLI with progress(1) injected into HTML
            raw_html = html_path.read_text(encoding="utf-8")
            inject_script = """
            <script>
            window.addEventListener('load', () => {
                setTimeout(() => {
                    const tls = Object.values(window.__timelines || {});
                    for (const tl of tls) {
                        if (typeof tl.progress === 'function') tl.progress(1);
                    }
                }, 100);
            });
            </script>
            """
            injected_html = raw_html.replace("</body>", f"{inject_script}</body>")
            injected_file = workdir / "injected_still.html"
            injected_file.write_text(injected_html, encoding="utf-8")
            file_url = injected_file.resolve().as_uri()

            chrom_cmd = [
                chrom_exe,
                "--headless=new",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--hide-scrollbars",
                "--window-size=1080,1920",
                "--virtual-time-budget=2000",
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
                still_captured = png_path.is_file() and png_path.stat().st_size > 0
            except Exception as e:
                logger.warning("Chromium CLI still capture failed: %s", e)

        if still_captured:
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
                logger.info("Motion graphic conversion succeeded (mg_path=still)")
                return out_path

    # 4. Both failed or no converters available
    raise RuntimeError(
        "Motion graphic HTML conversion failed: converters unavailable or execution failed"
    )
