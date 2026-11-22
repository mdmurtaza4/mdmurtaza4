"""Pause detection and keep-segment calculation.

Cuts are decided on audio energy (FFmpeg silencedetect), then any cut that would
clip a transcribed word is shrunk. Transcript gaps alone are unreliable because
Whisper word timestamps can drift by a few hundred milliseconds.
"""

from __future__ import annotations

import re
from pathlib import Path

from .edl import Segment, Word
from .tools import ffmpeg_bin, run

_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_END = re.compile(r"silence_end:\s*(-?[\d.]+)")


def detect_silences(path: str | Path, noise_db: float = -35.0, min_silence: float = 0.6) -> list[tuple[float, float]]:
    proc = run(
        [
            ffmpeg_bin(), "-hide_banner", "-nostats", "-i", str(path), "-vn",
            "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}", "-f", "null", "-",
        ]
    )
    silences: list[tuple[float, float]] = []
    start: float | None = None
    for line in proc.stderr.splitlines():
        if (m := _START.search(line)) is not None:
            start = max(0.0, float(m.group(1)))
        elif (m := _END.search(line)) is not None and start is not None:
            silences.append((start, float(m.group(1))))
            start = None
    if start is not None:  # silence runs to the end of file
        silences.append((start, float("inf")))
    return silences


def _subtract(interval: tuple[float, float], blockers: list[tuple[float, float]]) -> list[tuple[float, float]]:
    pieces = [interval]
    for b0, b1 in blockers:
        nxt = []
        for p0, p1 in pieces:
            if b1 <= p0 or b0 >= p1:
                nxt.append((p0, p1))
                continue
            if b0 > p0:
                nxt.append((p0, b0))
            if b1 < p1:
                nxt.append((b1, p1))
        pieces = nxt
    return pieces


def keep_segments(
    duration: float,
    silences: list[tuple[float, float]],
    words: list[Word] | None = None,
    padding: float = 0.15,
    min_cut: float = 0.35,
    min_keep: float = 0.25,
) -> list[Segment]:
    """Turn detected silences into the spans to keep.

    padding  - breathing room retained either side of speech so cuts feel natural
    min_cut  - removed spans shorter than this are left in (avoids choppy edits)
    min_keep - kept spans shorter than this are dropped (stray clicks, coughs)
    """
    protect = [(w.start - 0.05, w.end + 0.05) for w in (words or [])]
    cuts: list[tuple[float, float]] = []
    for s0, s1 in silences:
        s1 = min(s1, duration)
        c0 = s0 + padding if s0 > 0 else 0.0
        c1 = s1 - padding if s1 < duration else duration
        for p0, p1 in _subtract((c0, c1), protect):
            if p1 - p0 >= min_cut:
                cuts.append((p0, p1))
    cuts.sort()

    keeps: list[Segment] = []
    cursor = 0.0
    for c0, c1 in cuts:
        if c0 - cursor >= min_keep:
            keeps.append(Segment(start=round(cursor, 3), end=round(c0, 3)))
        cursor = max(cursor, c1)
    if duration - cursor >= min_keep:
        keeps.append(Segment(start=round(cursor, 3), end=round(duration, 3)))
    if not keeps:  # never produce an empty edit
        keeps = [Segment(start=0.0, end=round(duration, 3))]
    return keeps
