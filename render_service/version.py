"""Render engine version (bug B3 / E2-05).

Bump this string whenever a change affects the manifest, the RenderIR contract,
or how a renderer (`ffmpeg_dress.py`, `ffmpeg_raw.py`, `motion.py`) draws a frame,
so a re-render after the fix produces a new MP4 instead of reusing a cached one.
"""

ENGINE_VERSION = "2026.09.27-1"
