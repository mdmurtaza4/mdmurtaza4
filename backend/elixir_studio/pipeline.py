"""Milestone-1 pipeline: import -> transcribe -> cut pauses -> captions -> enhance -> render -> QA.

Each step writes its result into the project folder, so an interrupted job resumes
from the last completed step instead of starting again.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

from . import media, qa, silence
from .edl import EDL, ExportSettings, Segment
from .hardware import detect
from .render import render
from .transcribe import Transcript, transcribe

log = logging.getLogger(__name__)
Progress = Callable[[str, float], None]


def _noop(stage: str, pct: float) -> None:
    log.info("[%3.0f%%] %s", pct * 100, stage)


def analyse(project_dir: Path, source: Path, model: str | None = None, device: str | None = None,
            language: str | None = None, transcribe_speech: bool = True, progress: Progress = _noop) -> EDL:
    project_dir.mkdir(parents=True, exist_ok=True)
    edl_path = project_dir / "project.json"
    if edl_path.exists():
        existing = EDL.load(edl_path)
        if Path(existing.source).resolve() == source.resolve():
            progress("Project already analysed; reusing saved edit", 1.0)
            return existing

    progress("Inspecting footage", 0.02)
    info = media.probe(source)
    if not info.has_audio:
        raise ValueError(f"{source.name} has no audio track; a speech edit needs audio.")
    (project_dir / "media.json").write_text(json.dumps(info.to_dict(), indent=2), encoding="utf-8")

    progress("Extracting speech audio", 0.08)
    wav = project_dir / "cache" / "speech.wav"
    if not wav.exists():
        media.extract_audio(source, wav)

    words = []
    lang = None
    tpath = project_dir / "transcript.json"
    if transcribe_speech:
        if tpath.exists():
            t = Transcript.load(tpath)
        else:
            hw = detect()
            plan = hw.whisper
            progress(f"Transcribing with Whisper {model or plan.model} ({device or plan.device})", 0.15)
            t = transcribe(wav, model=model or plan.model, device=device or plan.device, language=language)
            t.save(tpath)
        words, lang = t.words, t.language

    progress("Finding pauses", 0.7)
    silences = silence.detect_silences(wav)
    segments = silence.keep_segments(info.duration, silences, words)

    edl = EDL(source=str(source.resolve()), source_duration=info.duration, segments=segments,
              words=words, transcript_language=lang)
    edl.save(edl_path)
    progress("Analysis complete", 1.0)
    return edl


def produce(project_dir: Path, preset: str = "vertical", output: Path | None = None,
            progress: Progress = _noop) -> tuple[Path, qa.QAReport]:
    edl = EDL.load(project_dir / "project.json")
    edl.export = ExportSettings(**{**edl.export.model_dump(), "preset": preset})
    edl.save(project_dir / "project.json")
    output = output or project_dir / "output" / f"{Path(edl.source).stem}_{preset}.mp4"

    progress(f"Rendering {preset} video", 0.1)
    result = render(edl, output, project_dir / "cache" / preset)
    progress(f"Checking quality (encoder: {result.encoder})", 0.9)
    report = qa.check(result.output, edl)
    (project_dir / "output" / f"qa_{preset}.json").write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    progress("Done", 1.0)
    return result.output, report


def set_segments(project_dir: Path, segments: list[dict]) -> EDL:
    """Apply a manual edit from the UI (e.g. restore a pause the teacher wants kept)."""
    edl = EDL.load(project_dir / "project.json")
    edl.segments = [Segment(**s) for s in segments]
    edl = EDL.model_validate(edl.model_dump())
    edl.save(project_dir / "project.json")
    return edl
