import shutil
import subprocess
from pathlib import Path

import pytest

SENTENCES = [
    "Good morning everyone. Welcome to The ELiXIR School.",
    "Today I will speak about why reading matters.",
    "Thank you for listening.",
]
PAUSE = 2.0


def _ff(*args: str) -> None:
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args], check=True)


@pytest.fixture(scope="session")
def speech_video(tmp_path_factory) -> Path:
    """A 1280x720 'student speech' clip: synthetic voice with long pauses and light room noise."""
    if not shutil.which("espeak-ng"):
        pytest.skip("espeak-ng not installed")
    d = tmp_path_factory.mktemp("fixture")
    parts = []
    for i, s in enumerate(SENTENCES):
        wav = d / f"s{i}.wav"
        subprocess.run(["espeak-ng", "-s", "150", "-w", str(wav), s], check=True)
        parts.append(wav)
    silence = d / "pause.wav"
    _ff("-f", "lavfi", "-i", "anullsrc=r=22050:cl=mono", "-t", str(PAUSE), str(silence))
    listing = d / "list.txt"
    seq = [silence]
    for p in parts:
        seq += [p, silence]
    listing.write_text("".join(f"file '{p}'\n" for p in seq))
    speech = d / "speech.wav"
    _ff("-f", "concat", "-safe", "0", "-i", str(listing), "-ar", "48000", "-ac", "1", str(speech))
    video = d / "student_speech.mp4"
    _ff(
        "-i", str(speech), "-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.003:r=48000",
        "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30",
        "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=first:normalize=0[a]",
        "-map", "2:v", "-map", "[a]", "-shortest", "-c:v", "libx264", "-preset", "ultrafast",
        "-c:a", "aac", str(video),
    )
    return video
