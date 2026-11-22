"""Edit Decision List: the editable, non-destructive description of a finished video.

AI analysis writes an EDL; the renderer executes it. Re-rendering after a correction
never requires repeating transcription.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

EDL_VERSION = 1


class Word(BaseModel):
    text: str
    start: float
    end: float
    probability: float = 1.0


class Segment(BaseModel):
    """A span of the source to keep, in source seconds."""

    start: float = Field(ge=0)
    end: float

    @model_validator(mode="after")
    def _ordered(self) -> Segment:
        if self.end <= self.start:
            raise ValueError(f"segment end ({self.end}) must be after start ({self.start})")
        return self

    @property
    def duration(self) -> float:
        return self.end - self.start


class AudioSettings(BaseModel):
    enhance: bool = True
    highpass_hz: int = 80
    denoise_floor_db: int = -25
    presence_gain_db: float = 2.5
    target_lufs: float = -14.0
    true_peak_db: float = -1.5


class ColorSettings(BaseModel):
    # Global, whole-frame adjustments only. No face- or skin-specific processing, ever.
    mode: Literal["none", "subtle"] = "none"
    contrast: float = 1.04
    saturation: float = 1.06
    brightness: float = 0.0


class CaptionSettings(BaseModel):
    enabled: bool = True
    max_chars: int = 28
    max_words: int = 6
    max_duration: float = 3.0
    highlight_active_word: bool = True
    font: str = "Arial"


class BrandingSettings(BaseModel):
    watermark: bool = True
    logo_path: str | None = None  # official logo PNG; generated wordmark used when absent
    opacity: float = Field(default=0.9, ge=0, le=1)


class ExportSettings(BaseModel):
    preset: Literal["vertical", "landscape", "square"] = "vertical"
    framing: Literal["fit_blur", "crop"] = "fit_blur"
    fps: int = 30
    encoder: Literal["auto", "nvenc", "x264"] = "auto"
    quality: int = Field(default=19, ge=10, le=35)
    audio_bitrate: str = "192k"


class EDL(BaseModel):
    version: int = EDL_VERSION
    source: str
    source_duration: float
    segments: list[Segment]
    words: list[Word] = []
    transcript_language: str | None = None
    transcript_reviewed: bool = False
    audio: AudioSettings = AudioSettings()
    color: ColorSettings = ColorSettings()
    captions: CaptionSettings = CaptionSettings()
    branding: BrandingSettings = BrandingSettings()
    export: ExportSettings = ExportSettings()

    @model_validator(mode="after")
    def _check_segments(self) -> EDL:
        if not self.segments:
            raise ValueError("EDL must keep at least one segment")
        prev_end = -1.0
        for seg in self.segments:
            if seg.start < prev_end:
                raise ValueError("segments must be sorted and non-overlapping")
            if seg.end > self.source_duration + 0.05:
                raise ValueError(f"segment ends at {seg.end}s, beyond source ({self.source_duration}s)")
            prev_end = seg.end
        return self

    @property
    def output_duration(self) -> float:
        return sum(s.duration for s in self.segments)

    def save(self, path: str | Path) -> Path:
        """Atomic write so a crash mid-save never corrupts a project."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".edl-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(self.model_dump_json(indent=2))
        os.replace(tmp, path)
        return path

    @classmethod
    def load(cls, path: str | Path) -> EDL:
        return cls.model_validate(json.loads(Path(path).read_text(encoding="utf-8")))


def map_time(t: float, segments: list[Segment]) -> float | None:
    """Map a source timestamp to output time, or None if it falls in a removed span."""
    offset = 0.0
    for seg in segments:
        if seg.start <= t <= seg.end:
            return offset + (t - seg.start)
        offset += seg.duration
    return None


def remap_words(words: list[Word], segments: list[Segment]) -> list[Word]:
    """Move words onto the output timeline, clamping words that straddle a cut."""
    out: list[Word] = []
    offset = 0.0
    for seg in segments:
        for w in words:
            if w.end <= seg.start or w.start >= seg.end:
                continue
            start = max(w.start, seg.start) - seg.start + offset
            end = min(w.end, seg.end) - seg.start + offset
            if end - start >= 0.04:
                out.append(Word(text=w.text, start=round(start, 3), end=round(end, 3), probability=w.probability))
        offset += seg.duration
    out.sort(key=lambda w: w.start)
    return out
