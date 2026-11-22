"""Media inspection and proxy generation. Source files are only ever read."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path

from .tools import ToolError, ffmpeg_bin, ffprobe_json, run


@dataclass
class MediaInfo:
    path: str
    duration: float
    width: int
    height: int
    fps: float
    video_codec: str
    has_audio: bool
    audio_codec: str | None
    sample_rate: int | None
    rotation: int
    variable_frame_rate: bool

    @property
    def display_width(self) -> int:
        return self.height if self.rotation in (90, 270) else self.width

    @property
    def display_height(self) -> int:
        return self.width if self.rotation in (90, 270) else self.height

    def to_dict(self) -> dict:
        d = asdict(self)
        d["display_width"] = self.display_width
        d["display_height"] = self.display_height
        return d


def _rate(value: str | None) -> float:
    if not value or value in ("0/0", "0"):
        return 0.0
    return float(Fraction(value))


def probe(path: str | Path) -> MediaInfo:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    data = ffprobe_json(path)
    streams = data.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    if video is None:
        raise ToolError(f"{path.name} contains no video stream")

    rotation = 0
    for sd in video.get("side_data_list", []) or []:
        if "rotation" in sd:
            rotation = int(abs(int(sd["rotation"]))) % 360
    if "rotate" in (video.get("tags") or {}):
        rotation = int(video["tags"]["rotate"]) % 360

    r_rate = _rate(video.get("r_frame_rate"))
    avg_rate = _rate(video.get("avg_frame_rate"))
    fps = avg_rate or r_rate
    # Phone footage is frequently variable frame rate; we always normalise to a fixed rate on render.
    vfr = bool(r_rate and avg_rate and abs(r_rate - avg_rate) / r_rate > 0.01)

    duration = float(data.get("format", {}).get("duration") or video.get("duration") or 0)
    return MediaInfo(
        path=str(path.resolve()),
        duration=duration,
        width=int(video.get("width", 0)),
        height=int(video.get("height", 0)),
        fps=round(fps, 3),
        video_codec=video.get("codec_name", "unknown"),
        has_audio=audio is not None,
        audio_codec=audio.get("codec_name") if audio else None,
        sample_rate=int(audio["sample_rate"]) if audio and audio.get("sample_rate") else None,
        rotation=rotation,
        variable_frame_rate=vfr,
    )


def make_proxy(source: str | Path, dest: str | Path, height: int = 720) -> Path:
    """Create a lightweight 720p editing proxy. Never modifies the source."""
    source, dest = Path(source), Path(dest)
    if source.resolve() == dest.resolve():
        raise ValueError("Proxy destination must differ from the source file")
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
            "-vf", f"scale=-2:{height}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
            "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(dest),
        ]
    )
    return dest


def extract_audio(source: str | Path, dest: str | Path) -> Path:
    """16 kHz mono WAV for speech analysis."""
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            ffmpeg_bin(), "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dest),
        ]
    )
    return dest
