"""Caption grouping and ASS (Advanced SubStation) generation with active-word highlight."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .edl import CaptionSettings, Word

PRESETS = {
    "vertical": {"size": (1080, 1920), "font_size": 66, "margin_v": 430},
    "landscape": {"size": (1920, 1080), "font_size": 58, "margin_v": 90},
    "square": {"size": (1080, 1080), "font_size": 58, "margin_v": 150},
}

# ELiXIR palette in ASS &HAABBGGRR order
WHITE = "&H00FFFFFF"
NAVY = "&H005B2A0B"      # #0B2A5B
SKY = "&H00F8BD38"       # #38BDF8
SHADOW = "&H80000000"


@dataclass
class Cue:
    start: float
    end: float
    words: list[Word]

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


def group_cues(words: list[Word], cfg: CaptionSettings) -> list[Cue]:
    cues: list[Cue] = []
    cur: list[Word] = []
    for w in words:
        if cur:
            text_len = len(" ".join(x.text for x in cur)) + 1 + len(w.text)
            gap = w.start - cur[-1].end
            sentence_end = cur[-1].text.endswith((".", "?", "!", ","))
            if (
                text_len > cfg.max_chars
                or len(cur) >= cfg.max_words
                or w.end - cur[0].start > cfg.max_duration
                or gap > 0.6
                or (sentence_end and len(cur) >= 2)
            ):
                cues.append(Cue(cur[0].start, cur[-1].end, cur))
                cur = []
        cur.append(w)
    if cur:
        cues.append(Cue(cur[0].start, cur[-1].end, cur))
    # Hold each cue briefly after the last word, without overlapping the next.
    for i, c in enumerate(cues):
        limit = cues[i + 1].start if i + 1 < len(cues) else c.end + 0.4
        c.end = min(c.end + 0.25, limit)
    return cues


def _ts(t: float) -> str:
    cs = max(0, int(round(t * 100)))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def build_ass(words: list[Word], preset: str, cfg: CaptionSettings) -> str:
    p = PRESETS[preset]
    w, h = p["size"]
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{cfg.font},{p["font_size"]},{WHITE},{SKY},{NAVY},{SHADOW},-1,0,0,0,100,100,0,0,1,5,2,2,80,80,{p["margin_v"]},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    for cue in group_cues(words, cfg):
        if not cfg.highlight_active_word:
            lines.append(f"Dialogue: 0,{_ts(cue.start)},{_ts(cue.end)},Caption,,0,0,0,,{_esc(cue.text)}")
            continue
        for i, word in enumerate(cue.words):
            start = cue.start if i == 0 else word.start
            end = cue.words[i + 1].start if i + 1 < len(cue.words) else cue.end
            if end <= start:
                continue
            parts = [
                f"{{\\c{SKY}}}{_esc(x.text)}{{\\c{WHITE}}}" if j == i else _esc(x.text)
                for j, x in enumerate(cue.words)
            ]
            lines.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},Caption,,0,0,0,,{' '.join(parts)}")
    return header + "\n".join(lines) + "\n"


def build_srt(words: list[Word], cfg: CaptionSettings) -> str:
    """Plain SRT sidecar for YouTube / accessibility uploads."""

    def ts(t: float) -> str:
        ms = int(round(t * 1000))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    out = []
    for i, c in enumerate(group_cues(words, cfg), 1):
        out.append(f"{i}\n{ts(c.start)} --> {ts(c.end)}\n{c.text}\n")
    return "\n".join(out)


def write_captions(words: list[Word], preset: str, cfg: CaptionSettings, folder: Path) -> tuple[Path, Path]:
    folder.mkdir(parents=True, exist_ok=True)
    ass = folder / "captions.ass"
    srt = folder / "captions.srt"
    ass.write_text(build_ass(words, preset, cfg), encoding="utf-8")
    srt.write_text(build_srt(words, cfg), encoding="utf-8")
    return ass, srt
