"""End-to-end tests on a real (synthetic) speech video. Uses Whisper 'tiny' on CPU for speed;
set ELIXIR_TEST_MODEL=small to test the production model."""

import hashlib
import os

import pytest

from elixir_studio import media, pipeline
from elixir_studio.edl import EDL
from elixir_studio.hardware import detect

MODEL = os.environ.get("ELIXIR_TEST_MODEL", "tiny")


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_hardware_report_verifies_encoders():
    hw = detect()
    assert "libx264" in hw.encoders_working
    # An encoder may be listed without working (e.g. NVENC with no GPU); it must not be selected then.
    if hw.video_encoder == "h264_nvenc":
        assert "h264_nvenc" in hw.encoders_working


@pytest.mark.slow
def test_full_milestone(speech_video, tmp_path):
    before = sha(speech_video)
    project = tmp_path / "proj"
    edl = pipeline.analyse(project, speech_video, model=MODEL, device="cpu", language="en")

    src = media.probe(speech_video)
    assert len(edl.words) >= 15, "speech should be transcribed"
    assert edl.output_duration < src.duration - 3, "long pauses should be removed"
    joined = " ".join(w.text.lower() for w in edl.words)
    assert "reading" in joined and "listening" in joined

    for preset in ("vertical", "landscape", "square"):
        out, report = pipeline.produce(project, preset)
        failed = [c for c in report.checks if c.blocking and not c.passed]
        assert not failed, failed
        assert out.with_suffix(".srt").exists()

    # Analysis is resumable: a second call reuses the saved project.
    again = pipeline.analyse(project, speech_video, model=MODEL, device="cpu")
    assert again == EDL.load(project / "project.json")
    assert sha(speech_video) == before, "original footage must never change"


def test_render_without_transcription(speech_video, tmp_path):
    project = tmp_path / "p2"
    edl = pipeline.analyse(project, speech_video, transcribe_speech=False)
    assert not edl.words and len(edl.segments) >= 3
    out, report = pipeline.produce(project, "square")
    assert report.passed, report.to_dict()


def test_refuses_to_overwrite_source(speech_video, tmp_path):
    project = tmp_path / "p3"
    pipeline.analyse(project, speech_video, transcribe_speech=False)
    with pytest.raises(ValueError):
        pipeline.produce(project, "vertical", output=speech_video)
