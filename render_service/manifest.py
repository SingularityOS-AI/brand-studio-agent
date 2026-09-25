"""Render service manifest contract definitions (pydantic v2)."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CANVAS_W = 1080
CANVAS_H = 1920
CANVAS_FPS = 30

FONT_ALLOWLIST = ("Inter", "Montserrat", "Poppins", "Bebas Neue", "Anton", "Roboto")

HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

TRANSITIONS = ("cut", "flash", "zoom_through", "whip")
ZOOM_EASES = ("linear", "out")
OVERLAY_KINDS = (
    "onscreen_text",
    "card_stat",
    "card_quote",
    "card_list",
    "card_lower_third",
    "broll_card",
    "emoji",
)
INPUT_KINDS = ("video", "image", "audio", "html")
ERROR_CODES = ("bad_manifest", "fetch_failed", "ffmpeg_failed", "too_large", "timeout")


class Canvas(BaseModel):
    model_config = ConfigDict(extra="forbid")

    w: int = Field(default=CANVAS_W)
    h: int = Field(default=CANVAS_H)
    fps: int = Field(default=CANVAS_FPS)

    @field_validator("w")
    @classmethod
    def validate_w(cls, v: int) -> int:
        if v != CANVAS_W:
            raise ValueError(f"Canvas width must be {CANVAS_W}")
        return v

    @field_validator("h")
    @classmethod
    def validate_h(cls, v: int) -> int:
        if v != CANVAS_H:
            raise ValueError(f"Canvas height must be {CANVAS_H}")
        return v

    @field_validator("fps")
    @classmethod
    def validate_fps(cls, v: int) -> int:
        if v != CANVAS_FPS:
            raise ValueError(f"Canvas fps must be {CANVAS_FPS}")
        return v


class TimelineSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gap_ms: int = Field(ge=0)
    pad_ms: int = Field(ge=0)
    music_volume: float = Field(ge=0.0, le=1.0)
    music_muted: bool
    sfx_enabled: bool


class Segment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    in_ms: int = Field(ge=0)
    out_ms: int = Field(ge=0)
    out_start_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_times(self) -> Segment:
        if self.out_ms <= self.in_ms:
            raise ValueError("Segment out_ms must be greater than in_ms")
        return self


class Trim(BaseModel):
    """Founder's ±0.5 s adjustment: positive cuts more, negative keeps more air."""

    model_config = ConfigDict(extra="forbid")

    start_ms: int = Field(ge=-500, le=500)
    end_ms: int = Field(ge=-500, le=500)


class Broll(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["stock", "ai_image", "ai_video", "motion_graphic"]
    input_id: str
    w: int | None = Field(default=None, ge=1)
    h: int | None = Field(default=None, ge=1)
    duration_ms: int | None = Field(default=None, ge=0)


class TimelineScene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n: int = Field(ge=1)
    phase: str
    visual: Literal["face", "broll"]
    take_job_id: str
    take_input: str
    broll: Broll | None = None
    segments: list[Segment] = Field(min_length=1)
    trim: Trim
    out_start_ms: int = Field(ge=0)
    out_end_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_out_times(self) -> TimelineScene:
        if self.out_end_ms <= self.out_start_ms:
            raise ValueError("TimelineScene out_end_ms must be greater than out_start_ms")
        return self


class TimelineMusic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_id: str
    volume: float = Field(ge=0.0, le=1.0)


class Timeline(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    schema: Literal["brandstudio.timeline.v1"]
    edit_version: int = Field(ge=1)
    canvas: Canvas
    settings: TimelineSettings
    scenes: list[TimelineScene] = Field(min_length=1)
    music: TimelineMusic | None = None
    duration_ms: int = Field(ge=0)
    hash: str


class CaptionWord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^s\d+w\d+$")
    scene_n: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=40)
    edited_text: str | None = Field(default=None, max_length=40)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_times(self) -> CaptionWord:
        if self.end_ms < self.start_ms:
            raise ValueError("CaptionWord end_ms must be >= start_ms")
        return self


class CaptionStyle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    font: str
    text: str
    accent: str
    outline: str

    @field_validator("font")
    @classmethod
    def validate_font(cls, v: str) -> str:
        if v not in FONT_ALLOWLIST:
            raise ValueError(f"Font '{v}' not in FONT_ALLOWLIST: {FONT_ALLOWLIST}")
        return v

    @field_validator("text", "accent", "outline")
    @classmethod
    def validate_hex_color(cls, v: str) -> str:
        if not HEX_RE.match(v):
            raise ValueError(f"Color '{v}' must be hex format #RRGGBB")
        return v


class Captions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    words: list[CaptionWord]
    style: CaptionStyle


class FrameZero(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=80)
    start_ms: int = Field(default=0, ge=0)
    end_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_times(self) -> FrameZero:
        if self.end_ms < self.start_ms:
            raise ValueError("FrameZero end_ms must be >= start_ms")
        return self


class CaptionToken(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=40)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_times(self) -> CaptionToken:
        if self.end_ms < self.start_ms:
            raise ValueError("CaptionToken end_ms must be >= start_ms")
        return self


class CaptionEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    lines: list[list[CaptionToken]] = Field(min_length=1, max_length=2)
    size: Literal["hero", "block"]
    emphasis: list[int]

    @model_validator(mode="after")
    def validate_lines_and_times(self) -> CaptionEvent:
        if self.end_ms < self.start_ms:
            raise ValueError("CaptionEvent end_ms must be >= start_ms")
        if not (1 <= len(self.lines) <= 2):
            raise ValueError("CaptionEvent lines must have 1 or 2 lines")
        for line in self.lines:
            if not (1 <= len(line) <= 3):
                raise ValueError("CaptionEvent line must contain 1 to 3 tokens")
        return self


class ZoomKey(BaseModel):
    model_config = ConfigDict(extra="forbid")

    t_ms: int = Field(ge=0)
    scale: float = Field(ge=1.0, le=1.5)
    cx: float = Field(ge=0.0, le=1.0)
    cy: float = Field(ge=0.0, le=1.0)
    ease: Literal["linear", "out"]


class TransitionCue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at_ms: int = Field(ge=0)
    type: Literal["cut", "flash", "zoom_through", "whip"]
    dur_ms: int = Field(ge=0, le=600)


class OverlayCue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9_-]{1,40}$")
    kind: Literal[
        "onscreen_text",
        "card_stat",
        "card_quote",
        "card_list",
        "card_lower_third",
        "broll_card",
        "emoji",
    ]
    asset: str | None = None
    text: str | None = Field(default=None, max_length=80)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    x: int = Field(ge=0, le=1080)
    y: int = Field(ge=0, le=1920)
    w: int = Field(ge=0, le=1080)
    h: int = Field(ge=0, le=1920)
    anim: Literal["pop"]

    @model_validator(mode="after")
    def validate_times_and_bounds(self) -> OverlayCue:
        if self.end_ms < self.start_ms:
            raise ValueError("OverlayCue end_ms must be >= start_ms")
        return self


class SfxCue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at_ms: int = Field(ge=0)
    input_id: str
    gain_db: float = Field(ge=-30.0, le=6.0)


class RenderIR(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    schema: Literal["brandstudio.ir.v1"]
    duration_ms: int = Field(ge=0)
    frame_zero: FrameZero | None = None
    captions: list[CaptionEvent] = Field(default_factory=list)
    zoom_keys: list[ZoomKey] = Field(default_factory=list)
    transitions: list[TransitionCue] = Field(default_factory=list)
    overlays: list[OverlayCue] = Field(default_factory=list)
    sfx: list[SfxCue] = Field(default_factory=list)
    style: CaptionStyle

    @model_validator(mode="after")
    def validate_duration(self) -> RenderIR:
        dur = self.duration_ms
        if self.frame_zero and self.frame_zero.end_ms > dur:
            raise ValueError(
                f"frame_zero end_ms ({self.frame_zero.end_ms}) > duration_ms ({dur})"
            )
        for event in self.captions:
            if event.end_ms > dur:
                raise ValueError(
                    f"caption event end_ms ({event.end_ms}) > duration_ms ({dur})"
                )
        for zk in self.zoom_keys:
            if zk.t_ms > dur:
                raise ValueError(
                    f"zoom_key t_ms ({zk.t_ms}) > duration_ms ({dur})"
                )
        for tr in self.transitions:
            if tr.at_ms > dur:
                raise ValueError(
                    f"transition at_ms ({tr.at_ms}) > duration_ms ({dur})"
                )
        for ov in self.overlays:
            if ov.end_ms > dur:
                raise ValueError(
                    f"overlay end_ms ({ov.end_ms}) > duration_ms ({dur})"
                )
        for sfx in self.sfx:
            if sfx.at_ms > dur:
                raise ValueError(
                    f"sfx at_ms ({sfx.at_ms}) > duration_ms ({dur})"
                )
        return self


class InputRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    kind: Literal["video", "image", "audio", "html"]
    w: int | None = Field(default=None, ge=1)
    h: int | None = Field(default=None, ge=1)

    @field_validator("url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("InputRef url must start with https://")
        return v


class ConvertItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_id: str
    upload_url: str
    storage_path: str

    @field_validator("upload_url")
    @classmethod
    def validate_upload_url(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("ConvertItem upload_url must start with https://")
        return v


class OutputTarget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upload_url: str
    storage_path: str
    max_bytes: int = Field(default=47_000_000, ge=1, le=50_000_000)

    @field_validator("upload_url")
    @classmethod
    def validate_upload_url(cls, v: str) -> str:
        if not v.startswith("https://"):
            raise ValueError("OutputTarget upload_url must start with https://")
        return v

    @field_validator("storage_path")
    @classmethod
    def validate_storage_path(cls, v: str) -> str:
        if not v.endswith(".mp4"):
            raise ValueError("OutputTarget storage_path must end with .mp4")
        return v


class RenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())

    schema: Literal["brandstudio.render.v1"]
    job_id: str
    attempt: int = Field(ge=1)
    mode: Literal["raw", "final"]
    timeline: Timeline | None = None
    ir: RenderIR | None = None
    raw_input_id: str | None = None
    inputs: dict[str, InputRef]
    convert: list[ConvertItem] = Field(default_factory=list)
    output: OutputTarget
    progress_url: str | None = None

    @field_validator("progress_url")
    @classmethod
    def validate_progress_url(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith("https://"):
            raise ValueError("progress_url must start with https://")
        return v

    @model_validator(mode="after")
    def validate_mode_and_refs(self) -> RenderRequest:
        if self.mode == "raw":
            if self.timeline is None:
                raise ValueError("mode='raw' requires timeline")
            if self.ir is not None:
                raise ValueError("mode='raw' forbids ir")
        elif self.mode == "final":
            if self.ir is None:
                raise ValueError("mode='final' requires ir")
            if self.raw_input_id is None:
                raise ValueError("mode='final' requires raw_input_id")
            if self.raw_input_id not in self.inputs:
                raise ValueError(
                    f"raw_input_id '{self.raw_input_id}' not found in inputs"
                )

        if self.timeline:
            for scene in self.timeline.scenes:
                if scene.take_input not in self.inputs:
                    raise ValueError(
                        f"take_input '{scene.take_input}' in scene {scene.n} not found in inputs"
                    )
                if scene.broll and scene.broll.input_id not in self.inputs:
                    raise ValueError(
                        f"broll input_id '{scene.broll.input_id}' in scene {scene.n} not found in inputs"
                    )
            if self.timeline.music and self.timeline.music.input_id not in self.inputs:
                raise ValueError(
                    f"music input_id '{self.timeline.music.input_id}' not found in inputs"
                )

        if self.ir:
            for sfx in self.ir.sfx:
                if sfx.input_id not in self.inputs:
                    raise ValueError(
                        f"sfx input_id '{sfx.input_id}' not found in inputs"
                    )

        return self


class RenderOk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: Literal[True] = True
    storage_path: str
    duration_ms: int = Field(ge=0)
    bytes: int = Field(ge=0)
    render_s: float = Field(ge=0.0)
    scene_marks_ms: list[int]
    converted: list[str] = Field(default_factory=list)


class RenderError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: Literal[False] = False
    code: Literal[
        "bad_manifest", "fetch_failed", "ffmpeg_failed", "too_large", "timeout"
    ]
    retryable: bool
    detail: str

    @field_validator("detail")
    @classmethod
    def sanitize_detail(cls, v: str) -> str:
        if not isinstance(v, str):
            return v
        cleaned = re.sub(r"(https?://[^\s?#]+)\?[^\s#]*", r"\1", v)
        if len(cleaned) > 500:
            cleaned = cleaned[:500]
        return cleaned


def canonical_json(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def timeline_hash(timeline_dict: dict) -> str:
    clean_dict = {k: v for k, v in timeline_dict.items() if k != "hash"}
    raw = canonical_json(clean_dict)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def hex_to_ass(color: str) -> str:
    if not isinstance(color, str) or not HEX_RE.match(color):
        raise ValueError(f"Invalid hex color: {color}")
    rr = color[1:3]
    gg = color[3:5]
    bb = color[5:7]
    return f"&H00{bb.upper()}{gg.upper()}{rr.upper()}"
