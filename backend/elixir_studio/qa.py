"""Quality assurance on a rendered file, before it is released for publishing."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .captions import PRESETS
from .edl import EDL
from .tools import ffmpeg_bin, ffprobe_json, run


@dataclass
class Check:
    name: str
    passed: bool
    detail: str
    blocking: bool = True


@dataclass
class QAReport:
    output: str
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks if c.blocking)

    def to_dict(self) -> dict:
        return {"output": self.output, "passed": self.passed, "checks": [asdict(c) for c in self.checks]}


def measure_loudness(path: Path) -> float | None:
    proc = run([ffmpeg_bin(), "-hide_banner", "-nostats", "-i", str(path), "-vn",
                "-af", "loudnorm=print_format=json", "-f", "null", "-"])
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", proc.stderr, re.S)
    if not m:
        return None
    return float(json.loads(m.group(0))["input_i"])


def check(output: str | Path, edl: EDL) -> QAReport:
    output = Path(output)
    rep = QAReport(str(output))
    if not output.exists():
        rep.checks.append(Check("file_exists", False, "Output file missing"))
        return rep
    data = ffprobe_json(output)
    streams = data.get("streams", [])
    v = next((s for s in streams if s["codec_type"] == "video"), None)
    a = next((s for s in streams if s["codec_type"] == "audio"), None)
    rep.checks.append(Check("video_stream", v is not None and v.get("codec_name") == "h264",
                            f"codec={v.get('codec_name') if v else None}"))
    rep.checks.append(Check("audio_stream", a is not None and a.get("codec_name") == "aac",
                            f"codec={a.get('codec_name') if a else None}, rate={a.get('sample_rate') if a else None}"))
    if v:
        want = PRESETS[edl.export.preset]["size"]
        got = (int(v["width"]), int(v["height"]))
        rep.checks.append(Check("resolution", got == want, f"{got[0]}x{got[1]} (expected {want[0]}x{want[1]})"))
        rep.checks.append(Check("pixel_format", v.get("pix_fmt") == "yuv420p", f"{v.get('pix_fmt')} (needed for phone playback)"))

    dur = float(data.get("format", {}).get("duration", 0))
    expected = edl.output_duration
    rep.checks.append(Check("duration", abs(dur - expected) <= 0.3, f"{dur:.2f}s (edit list: {expected:.2f}s)"))
    if v and a:
        drift = abs(float(v.get("duration", dur)) - float(a.get("duration", dur)))
        rep.checks.append(Check("av_sync", drift <= 0.1, f"stream length difference {drift * 1000:.0f} ms"))

    if edl.audio.enhance:
        lufs = measure_loudness(output)
        ok = lufs is not None and abs(lufs - edl.audio.target_lufs) <= 2.0
        rep.checks.append(Check("loudness", ok, f"{lufs} LUFS (target {edl.audio.target_lufs})", blocking=False))

    if edl.captions.enabled and edl.words:
        low = [w for w in edl.words if w.probability < 0.5]
        rep.checks.append(Check(
            "transcript_reviewed", edl.transcript_reviewed,
            "Transcript approved by a person" if edl.transcript_reviewed
            else f"Transcript not yet reviewed ({len(low)} low-confidence words). Review before publishing.",
            blocking=False,
        ))
    return rep
